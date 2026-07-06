#!/usr/bin/env python3
"""
coverage_stats.py — Per-gene coverage statistics across CRAM or .cov files.

Metrics reported per gene:
  min_mean_cov    Minimum mean depth across all samples
  max_mean_cov    Maximum mean depth across all samples
  min_pct_Nx      Minimum % of bases >= threshold (worst-case sample)
  mean_pct_Nx     Mean % of bases >= threshold across samples
  n_samples       Number of samples contributing to the statistics

Overlapping regions assigned to the same gene are merged before counting
to avoid double-counting bases.

Requirements:
  samtools >= 1.9 in PATH   (CRAM input only)
  helix_app_covetous         (.cov input only)
  Python >= 3.6

Input types
-----------
CRAM files  Use --cram / --cram-list.  Depth is computed on-the-fly via
            ``samtools depth``.  A reference FASTA may be required if not
            embedded in the CRAM headers (--reference).

.cov files  Use --cov / --cov-list.  Depth arrays are read directly from
            pre-computed .cov files via helix_app_covetous.open_covfile.
            --reference, --min-mapq, and --min-baseq are ignored.

SGE job array usage — CRAM input
---------------------------------
  # Step 1 — scatter
  qsub -t 1-N -tc <max_concurrent> \\
      coverage_stats.py \\
      --bed regions.bed --cram-list crams.txt \\
      --tmp-dir /scratch/cov_tmp [--reference ref.fa]

  # Step 2 — gather
  qsub -hold_jid <scatter_job_id> \\
      coverage_stats.py \\
      --bed regions.bed --cram-list crams.txt \\
      --tmp-dir /scratch/cov_tmp --gather -o out.tsv

SGE job array usage — .cov input
----------------------------------
  # Step 1 — scatter
  qsub -t 1-N -tc <max_concurrent> \\
      coverage_stats.py \\
      --bed regions.bed --cov-list covfiles.txt \\
      --tmp-dir /scratch/cov_tmp

  # Step 2 — gather
  qsub -hold_jid <scatter_job_id> \\
      coverage_stats.py \\
      --bed regions.bed --cov-list covfiles.txt \\
      --tmp-dir /scratch/cov_tmp --gather -o out.tsv

Single-node usage — CRAM input
--------------------------------
  python coverage_stats.py --bed regions.bed --cram a.cram b.cram -o out.tsv
  python coverage_stats.py --bed regions.bed --cram-list crams.txt -o out.tsv

  # If the reference is not embedded in the CRAM headers:
  python coverage_stats.py --bed regions.bed --cram-list crams.txt \\
      --reference ref.fa -o out.tsv

Single-node usage — .cov input
--------------------------------
  python coverage_stats.py --bed regions.bed --cov a.cov b.cov -o out.tsv
  python coverage_stats.py --bed regions.bed --cov-list covfiles.txt -o out.tsv

  # Custom depth threshold (applies to both input types):
  python coverage_stats.py --bed regions.bed --cov-list covfiles.txt \\
      --min-depth 10 -o out.tsv
"""

import argparse
import bisect
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


# Filename suffix used for per-sample intermediate files written by scatter.
_INTERMEDIATE_SUFFIX = ".per_sample.tsv"


def _import_covetous():
    """Lazy import of helix_app_covetous — only errors when the .cov path is taken."""
    try:
        from helix_app_covetous import open_covfile  # noqa: PLC0415
        return open_covfile
    except ImportError:
        sys.exit("Error: helix_app_covetous is required for --cov / --cov-list input.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Calculate per-gene coverage statistics from CRAM files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--bed", required=True,
        help="BED file of target regions; gene name must be in column 4.",
    )

    inp = parser.add_mutually_exclusive_group(required=True)
    inp.add_argument(
        "--cram", nargs="+",
        help="One or more CRAM files (indexes assumed at <cram>.crai).",
    )
    inp.add_argument(
        "--cram-list",
        help="Text file listing CRAM paths, one per line.",
    )
    inp.add_argument(
        "--cov", nargs="+", metavar="COV",
        help="One or more .cov files (read via helix_app_covetous).",
    )
    inp.add_argument(
        "--cov-list", metavar="FILE",
        help="Text file listing .cov paths, one per line.",
    )

    parser.add_argument(
        "--reference", "--ref",
        help=(
            "Reference FASTA for CRAM decoding (required if not embedded in CRAM headers). "
            "Ignored when using --cov / --cov-list."
        ),
    )
    parser.add_argument(
        "--min-depth", type=int, default=20,
        help="Depth threshold for the percentage metric (default: 20).",
    )
    parser.add_argument(
        "--min-mapq", type=int, default=0,
        help="Minimum mapping quality for reads (default: 0). Ignored when using --cov / --cov-list.",
    )
    parser.add_argument(
        "--min-baseq", type=int, default=0,
        help="Minimum base quality (default: 0). Ignored when using --cov / --cov-list.",
    )
    parser.add_argument(
        "--output", "-o",
        help="Output TSV file path. Required for gather and single-node modes.",
    )
    parser.add_argument(
        "--tmp-dir",
        help=(
            "Directory for per-sample intermediate files written during scatter "
            "and read during gather. Required for scatter and gather modes."
        ),
    )
    parser.add_argument(
        "--gather", action="store_true",
        help=(
            "Gather mode: read per-sample intermediates from --tmp-dir and "
            "aggregate them into the final output TSV (--output)."
        ),
    )
    parser.add_argument(
        "--task-id", type=int,
        help=(
            "1-based index of the CRAM to process in scatter mode. "
            "Defaults to $SGE_TASK_ID when running under SGE. "
            "Useful for local testing without a scheduler."
        ),
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# BED parsing
# ---------------------------------------------------------------------------

def parse_bed(bed_file):
    """
    Parse a BED file (gene name in column 4).

    Overlapping or adjacent regions assigned to the same gene are merged so
    that each base is counted at most once per sample.

    Returns
    -------
    gene_regions : dict[str, list[tuple[str, int, int]]]
        gene -> list of (chrom, start, end) after merging
    interval_lookup : dict[str, list[tuple[int, int, str]]]
        chrom -> sorted list of (start, end, gene) for fast position lookup
    """
    raw = defaultdict(list)  # gene -> [(chrom, start, end)]

    with open(bed_file) as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith(("#", "track", "browser")):
                continue
            cols = line.split("\t")
            if len(cols) < 4:
                print(
                    f"Warning: skipping BED line {lineno} - fewer than 4 columns.",
                    file=sys.stderr,
                )
                continue
            chrom = cols[0]
            try:
                start, end = int(cols[1]), int(cols[2])
            except ValueError:
                print(
                    f"Warning: skipping BED line {lineno} — non-integer coordinates.",
                    file=sys.stderr,
                )
                continue
            gene = cols[3]
            if start >= end:
                print(
                    f"Warning: skipping BED line {lineno} — start >= end.",
                    file=sys.stderr,
                )
                continue
            raw[gene].append((chrom, start, end))

    if not raw:
        sys.exit(f"Error: no valid regions parsed from '{bed_file}'.")

    gene_regions = {gene: _merge_intervals(regions) for gene, regions in raw.items()}

    # Build chrom-keyed interval list for O(log n) position → gene lookup
    interval_lookup = defaultdict(list)
    for gene, regions in gene_regions.items():
        for chrom, start, end in regions:
            interval_lookup[chrom].append((start, end, gene))
    for chrom in interval_lookup:
        interval_lookup[chrom].sort()

    return gene_regions, interval_lookup


def _merge_intervals(regions):
    """Merge overlapping/adjacent intervals, grouped per chromosome."""
    by_chrom = defaultdict(list)
    for chrom, start, end in regions:
        by_chrom[chrom].append((start, end))

    merged = []
    for chrom, ivs in by_chrom.items():
        ivs.sort()
        s, e = ivs[0]
        for ns, ne in ivs[1:]:
            if ns <= e:           # overlapping or adjacent
                e = max(e, ne)
            else:
                merged.append((chrom, s, e))
                s, e = ns, ne
        merged.append((chrom, s, e))
    return merged


def gene_total_bases(gene_regions):
    """Return dict[gene -> total base-pairs] summed across all merged regions."""
    return {
        gene: sum(end - start for _, start, end in regions)
        for gene, regions in gene_regions.items()
    }


# ---------------------------------------------------------------------------
# Position → gene lookup
# ---------------------------------------------------------------------------

def _find_gene(interval_lookup, chrom, pos_0based):
    """
    Return the gene name for a 0-based position, or None if not in any region.

    Uses bisect on the sorted (start, end, gene) list for the chromosome.
    """
    ivs = interval_lookup.get(chrom)
    if not ivs:
        return None
    # Rightmost interval whose start <= pos_0based
    idx = bisect.bisect_right(ivs, (pos_0based, float("inf"), "")) - 1
    if idx >= 0:
        start, end, gene = ivs[idx]
        if start <= pos_0based < end:
            return gene
    return None


# ---------------------------------------------------------------------------
# Per-CRAM processing
# ---------------------------------------------------------------------------

def process_cram(cram_path, bed_file, interval_lookup, total_bases,
                 reference, min_depth, min_mapq, min_baseq):
    """
    Run ``samtools depth`` for one CRAM file and accumulate per-gene stats.

    Returns
    -------
    mean_cov  : dict[gene -> float]  mean depth over the gene's merged regions
    pct_above : dict[gene -> float]  % of bases with depth >= min_depth
    """
    cmd = [
        "samtools", "depth",
        "-a",               # include zero-depth positions (required for accurate % calculation)
        "-b", bed_file,
        "-Q", str(min_mapq),
        "-q", str(min_baseq),
    ]
    if reference:
        cmd += ["--reference", reference]
    cmd.append(str(cram_path))

    depth_sum   = defaultdict(int)   # gene -> cumulative depth
    bases_above = defaultdict(int)   # gene -> bases >= threshold
    bases_seen  = defaultdict(int)   # gene -> positions emitted by samtools

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1 << 20,
        )

        for line in proc.stdout:
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            chrom   = parts[0]
            pos0    = int(parts[1]) - 1   # samtools depth is 1-based
            depth   = int(parts[2])
            gene    = _find_gene(interval_lookup, chrom, pos0)
            if gene is None:
                continue
            depth_sum[gene]  += depth
            bases_seen[gene] += 1
            if depth >= min_depth:
                bases_above[gene] += 1

        proc.wait()
        stderr_text = proc.stderr.read().strip()
        if proc.returncode != 0:
            print(
                f"Warning: samtools depth exited {proc.returncode} for {cram_path.name}:"
                f"\n  {stderr_text}",
                file=sys.stderr,
            )

    except FileNotFoundError:
        sys.exit(
            "Error: 'samtools' not found in PATH. "
            "Install samtools (>= 1.9) and ensure it is accessible."
        )

    # Convert to per-gene summary values
    mean_cov  = {}
    pct_above = {}
    for gene, tb in total_bases.items():
        denom = bases_seen.get(gene, 0) or tb   # prefer observed count; fall back to BED length
        mean_cov[gene]  = depth_sum.get(gene, 0) / denom
        pct_above[gene] = (bases_above.get(gene, 0) / denom) * 100.0

    return mean_cov, pct_above


def process_cov(cov_path, gene_regions, total_bases, min_depth):
    """
    Read a .cov file via helix_app_covetous and accumulate per-gene stats.

    Parameters
    ----------
    cov_path   : Path  – path to the .cov file
    gene_regions : dict[str, list[tuple[str, int, int]]]
        Merged intervals as returned by parse_bed (0-based half-open).
    total_bases : dict[str, int]  – total BED bases per gene (from gene_total_bases)
    min_depth   : int             – depth threshold for the percentage metric

    Returns
    -------
    mean_cov  : dict[gene -> float]
    pct_above : dict[gene -> float]
    """
    open_covfile = _import_covetous()
    cov = open_covfile(str(cov_path))

    depth_sum   = defaultdict(float)
    bases_above = defaultdict(int)
    bases_seen  = defaultdict(int)

    for gene, intervals in gene_regions.items():
        for chrom, start, end in intervals:          # 0-based half-open
            arr = cov.fetch_array(chrom, start, end) # NumPy array, length == (end - start)
            n = len(arr)
            if n == 0:
                continue
            depth_sum[gene]   += int(arr.sum())
            bases_above[gene] += int((arr >= min_depth).sum())
            bases_seen[gene]  += n

    mean_cov  = {}
    pct_above = {}
    for gene, tb in total_bases.items():
        denom = bases_seen.get(gene, 0) or tb
        mean_cov[gene]  = depth_sum.get(gene, 0) / denom
        pct_above[gene] = (bases_above.get(gene, 0) / denom) * 100.0

    return mean_cov, pct_above


# ---------------------------------------------------------------------------
# Scatter mode
# ---------------------------------------------------------------------------

def _sge_task_id():
    """Return $SGE_TASK_ID as an int, or None if not running under SGE."""
    val = os.environ.get("SGE_TASK_ID")
    if val and val != "undefined":
        try:
            return int(val)
        except ValueError:
            pass
    return None


def _run_scatter(args, input_files, task_id, tmp_dir):
    """Process a single input file (1-based task_id) and write an intermediate file."""
    n = len(input_files)
    if task_id < 1 or task_id > n:
        sys.exit(
            f"Error: task ID {task_id} is out of range "
            f"(valid range: 1–{n} for {n} input files)."
        )

    sample = input_files[task_id - 1]
    if not sample.exists():
        sys.exit(f"Error: input file not found: {sample}")

    print(f"Parsing BED file: {args.bed}", file=sys.stderr)
    gene_regions, interval_lookup = parse_bed(args.bed)
    total_bases = gene_total_bases(gene_regions)

    using_cov = bool(args.cov or args.cov_list)
    print(f"[task {task_id}/{n}] Processing {sample.name}", file=sys.stderr)
    if using_cov:
        mean_cov, pct_above = process_cov(sample, gene_regions, total_bases, args.min_depth)
    else:
        mean_cov, pct_above = process_cram(
            sample, args.bed, interval_lookup, total_bases,
            args.reference, args.min_depth, args.min_mapq, args.min_baseq,
        )

    out_path = tmp_dir / f"{task_id}{_INTERMEDIATE_SUFFIX}"
    with open(out_path, "w") as fh:
        fh.write("gene\tmean_cov\tpct_above\n")
        for gene in sorted(gene_regions):
            fh.write(f"{gene}\t{mean_cov[gene]:.6f}\t{pct_above[gene]:.6f}\n")

    print(f"Wrote intermediate: {out_path}", file=sys.stderr)
    print("Done.", file=sys.stderr)


# ---------------------------------------------------------------------------
# Gather mode
# ---------------------------------------------------------------------------

def _run_gather(args, cram_files, tmp_dir):
    """Aggregate per-sample intermediate files into the final output TSV."""
    n_crams = len(cram_files)
    # gene -> [n, min_cov, max_cov, sum_cov, min_pct, sum_pct]
    # Running aggregates avoid storing O(genes * samples) tuples in memory.
    agg = {}
    n_missing = 0

    for task_id in range(1, n_crams + 1):
        path = tmp_dir / f"{task_id}{_INTERMEDIATE_SUFFIX}"
        if not path.exists():
            n_missing += 1
            print(
                f"Warning: missing intermediate for task {task_id} "
                f"({cram_files[task_id - 1].name})",
                file=sys.stderr,
            )
            continue

        with open(path) as fh:
            fh.readline()   # skip header
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) != 3:
                    continue
                gene      = parts[0]
                mean_cov  = float(parts[1])
                pct_above = float(parts[2])
                if gene in agg:
                    a = agg[gene]
                    a[0] += 1
                    if mean_cov < a[1]: a[1] = mean_cov
                    if mean_cov > a[2]: a[2] = mean_cov
                    a[3] += mean_cov
                    if pct_above < a[4]: a[4] = pct_above
                    a[5] += pct_above
                else:
                    agg[gene] = [1, mean_cov, mean_cov, mean_cov, pct_above, pct_above]

    if n_missing:
        print(
            f"Warning: {n_missing} of {n_crams} intermediate file(s) missing. "
            "Results reflect only available samples.",
            file=sys.stderr,
        )

    threshold = args.min_depth
    print(f"Writing results to {args.output}", file=sys.stderr)

    with open(args.output, "w") as out:
        out.write("\t".join([
            "gene",
            "n_samples",
            "min_mean_cov",
            "max_mean_cov",
            "mean_mean_cov",
            f"min_pct_{threshold}x",
            f"mean_pct_{threshold}x",
        ]) + "\n")

        for gene in sorted(agg):
            a = agg[gene]
            n = a[0]
            out.write(
                f"{gene}\t{n}"
                f"\t{a[1]:.2f}"
                f"\t{a[2]:.2f}"
                f"\t{a[3] / n:.2f}"
                f"\t{a[4]:.2f}"
                f"\t{a[5] / n:.2f}"
                "\n"
            )

    print("Done.", file=sys.stderr)


# ---------------------------------------------------------------------------
# Single-node mode (original sequential behavior)
# ---------------------------------------------------------------------------

def _run_single_node(args, input_files):
    """Process all input files sequentially on a single node."""
    missing = [str(p) for p in input_files if not p.exists()]
    if missing:
        sys.exit("Error: the following input file(s) were not found:\n  " + "\n  ".join(missing))

    print(f"Parsing BED file: {args.bed}", file=sys.stderr)
    gene_regions, interval_lookup = parse_bed(args.bed)
    total_bases = gene_total_bases(gene_regions)
    n_genes = len(gene_regions)
    n_bases = sum(total_bases.values())
    print(
        f"  {n_genes} genes | {n_bases:,} total bases (after merging overlapping regions)",
        file=sys.stderr,
    )

    using_cov = bool(args.cov or args.cov_list)
    all_stats = defaultdict(list)

    for i, sample in enumerate(input_files, 1):
        print(f"[{i}/{len(input_files)}] {sample.name}", file=sys.stderr)
        if using_cov:
            mean_cov, pct_above = process_cov(sample, gene_regions, total_bases, args.min_depth)
        else:
            mean_cov, pct_above = process_cram(
                sample, args.bed, interval_lookup, total_bases,
                args.reference, args.min_depth, args.min_mapq, args.min_baseq,
            )
        for gene in gene_regions:
            all_stats[gene].append((mean_cov[gene], pct_above[gene]))

    threshold = args.min_depth
    print(f"Writing results to {args.output}", file=sys.stderr)

    with open(args.output, "w") as out:
        out.write("\t".join([
            "gene",
            "n_samples",
            "min_mean_cov",
            "max_mean_cov",
            "mean_mean_cov",
            f"min_pct_{threshold}x",
            f"mean_pct_{threshold}x",
        ]) + "\n")

        for gene in sorted(gene_regions):
            vals = all_stats.get(gene, [])
            n = len(vals)
            if n == 0:
                out.write(f"{gene}\t0\tNA\tNA\tNA\tNA\tNA\n")
                continue

            mean_covs = [v[0] for v in vals]
            pcts      = [v[1] for v in vals]

            out.write(
                f"{gene}\t{n}"
                f"\t{min(mean_covs):.2f}"
                f"\t{max(mean_covs):.2f}"
                f"\t{sum(mean_covs) / n:.2f}"
                f"\t{min(pcts):.2f}"
                f"\t{sum(pcts) / n:.2f}"
                "\n"
            )

    print("Done.", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _resolve_crams(args):
    """Return list of Path objects from --cram or --cram-list."""
    if args.cram:
        return [Path(p) for p in args.cram]
    cram_files = []
    with open(args.cram_list) as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                cram_files.append(Path(line))
    if not cram_files:
        sys.exit("Error: no CRAM files provided.")
    return cram_files


def _resolve_cov_files(args):
    """Return a list of Path objects from --cov or --cov-list."""
    if args.cov:
        return [Path(p) for p in args.cov]
    paths = []
    with open(args.cov_list) as fh:
        for line in fh:
            line = line.strip()
            if line:
                paths.append(Path(line))
    if not paths:
        sys.exit("Error: no .cov files provided.")
    return paths


def main():
    args = parse_args()

    using_cov = bool(args.cov or args.cov_list)
    if using_cov:
        if args.reference or args.min_mapq != 0 or args.min_baseq != 0:
            print(
                "Warning: --reference, --min-mapq, and --min-baseq are ignored "
                "when using --cov / --cov-list.",
                file=sys.stderr,
            )
        input_files = _resolve_cov_files(args)
    else:
        input_files = _resolve_crams(args)

    # Determine which mode to run.
    task_id = args.task_id or _sge_task_id()

    if task_id is not None:
        # ---- SCATTER MODE ----
        if not args.tmp_dir:
            sys.exit("Error: --tmp-dir is required for scatter mode.")
        tmp_dir = Path(args.tmp_dir)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        _run_scatter(args, input_files, task_id, tmp_dir)

    elif args.gather:
        # ---- GATHER MODE ----
        if not args.tmp_dir:
            sys.exit("Error: --tmp-dir is required for --gather.")
        if not args.output:
            sys.exit("Error: --output / -o is required for --gather.")
        tmp_dir = Path(args.tmp_dir)
        _run_gather(args, input_files, tmp_dir)

    else:
        # ---- SINGLE-NODE MODE ----
        if not args.output:
            sys.exit("Error: --output / -o is required.")
        _run_single_node(args, input_files)


if __name__ == "__main__":
    main()
