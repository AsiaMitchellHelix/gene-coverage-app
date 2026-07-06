"""
Resolve gene names, rsIDs, and genomic coordinates to gene names and BED regions.

At startup, builds an interval tree from the GTF (exon features only) so that
coordinate queries are O(log n). rsID lookup uses tabix over a local dbSNP VCF.
"""

import re
import tempfile
from pathlib import Path

import pysam
from intervaltree import Interval, IntervalTree

from app.config import settings

# chrom -> IntervalTree of (start, end, gene_name)
_interval_trees: dict[str, IntervalTree] = {}
# gene_name -> list of (chrom, start, end) exon intervals
_gene_exons: dict[str, list[tuple[str, int, int]]] = {}

_RSID_RE = re.compile(r"^rs\d+$", re.IGNORECASE)
_COORD_RE = re.compile(r"^(?:chr)?(\w+):(\d+)-(\d+)$")


def load_annotation() -> None:
    """Build interval trees and gene→exon index from the GTF at startup."""
    gtf = Path(settings.gtf_path)
    if not gtf.exists():
        raise FileNotFoundError(f"GTF not found: {gtf}")

    trees: dict[str, IntervalTree] = {}
    exons: dict[str, list[tuple[str, int, int]]] = {}

    with open(gtf) as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) < 9 or cols[2] != "exon":
                continue
            chrom = cols[0]
            start = int(cols[3]) - 1   # GTF is 1-based inclusive → 0-based half-open
            end = int(cols[4])
            attrs = cols[8]
            m = re.search(r'gene_name "([^"]+)"', attrs)
            if not m:
                m = re.search(r'gene_id "([^"]+)"', attrs)
            if not m:
                continue
            gene = m.group(1)

            trees.setdefault(chrom, IntervalTree()).addi(start, end, gene)
            exons.setdefault(gene, []).append((chrom, start, end))

    _interval_trees.update(trees)
    _gene_exons.update(exons)


def _rsid_to_chrom_pos(rsid: str) -> tuple[str, int] | None:
    """Return (chrom, 0-based pos) for an rsID using the tabix-indexed dbSNP VCF."""
    tbx = pysam.TabixFile(settings.dbsnp_vcf_path)
    for rec in tbx.fetch(parser=pysam.asVCF()):
        if rec.id == rsid:
            return rec.contig, rec.pos  # pos is already 0-based in pysam
    return None


def _coord_to_genes(chrom: str, start: int, end: int) -> list[str]:
    tree = _interval_trees.get(chrom) or _interval_trees.get(chrom.removeprefix("chr"))
    if not tree:
        return []
    hits = tree.overlap(start, end)
    return list({iv.data for iv in hits})


def resolve_identifiers(identifiers: list[str]) -> dict[str, list[str]]:
    """
    Map each identifier to a list of gene names.

    Returns a dict: identifier -> [gene, ...].
    Unresolvable identifiers map to an empty list.
    """
    result: dict[str, list[str]] = {}

    for ident in identifiers:
        ident = ident.strip()
        if not ident:
            continue

        if _RSID_RE.match(ident):
            loc = _rsid_to_chrom_pos(ident)
            if loc:
                chrom, pos = loc
                genes = _coord_to_genes(chrom, pos, pos + 1)
            else:
                genes = []

        elif m := _COORD_RE.match(ident):
            chrom = m.group(1)
            start, end = int(m.group(2)), int(m.group(3))
            genes = _coord_to_genes(chrom, start, end)

        else:
            # Treat as a gene name directly; validate it's in our annotation.
            genes = [ident] if ident in _gene_exons else []

        result[ident] = genes

    return result


def genes_to_bed(genes: list[str]) -> str:
    """
    Write a temporary BED file for the given genes (merged exon intervals).
    Returns the path to the temp file (caller is responsible for cleanup).
    """
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".bed", delete=False, prefix="gcov_"
    )
    for gene in sorted(genes):
        for chrom, start, end in sorted(_gene_exons.get(gene, [])):
            tmp.write(f"{chrom}\t{start}\t{end}\t{gene}\n")
    tmp.close()
    return tmp.name
