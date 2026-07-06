"""
Submit and monitor coverage_stats.py SGE job arrays on the Hcluster head node.
"""

import asyncio
import csv
import io
import logging
import re
from pathlib import Path, PurePosixPath
from uuid import UUID

import paramiko

from app.config import settings

log = logging.getLogger(__name__)

_POLL_INTERVAL = 30   # seconds between qstat checks


def _get_client() -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(
        hostname=settings.hcluster_host,
        username=settings.hcluster_user,
        key_filename=settings.hcluster_ssh_key_path,
    )
    return client


def _run(client: paramiko.SSHClient, cmd: str) -> tuple[int, str, str]:
    _, stdout, stderr = client.exec_command(cmd)
    exit_code = stdout.channel.recv_exit_status()
    return exit_code, stdout.read().decode(), stderr.read().decode()


def submit_job(job_id: UUID, bed_path_local: str) -> str:
    """
    Copy the BED file to scratch, submit scatter+gather SGE job array.
    Returns the gather SGE job ID string.
    """
    scratch = PurePosixPath(settings.hcluster_scratch_dir) / str(job_id)
    remote_bed = scratch / "regions.bed"
    remote_tmp = scratch / "tmp"
    remote_out = scratch / "coverage.tsv"
    script = PurePosixPath("/opt/coverage_stats/coverage_stats.py")

    client = _get_client()
    try:
        # Create scratch directory
        rc, _, err = _run(client, f"mkdir -p {remote_tmp}")
        if rc != 0:
            raise RuntimeError(f"mkdir failed: {err}")

        # Upload BED file
        sftp = client.open_sftp()
        sftp.put(bed_path_local, str(remote_bed))
        sftp.close()

        # Count samples for -t range
        rc, out, err = _run(client, f"wc -l < {settings.hcluster_cram_list}")
        if rc != 0:
            raise RuntimeError(f"wc -l failed: {err}")
        n_samples = int(out.strip())

        # Submit scatter array
        scatter_cmd = (
            f"qsub -t 1-{n_samples} -tc 50 -cwd -b y -V "
            f"python3 {script} "
            f"--bed {remote_bed} --cram-list {settings.hcluster_cram_list} "
            f"--tmp-dir {remote_tmp}"
        )
        rc, out, err = _run(client, scatter_cmd)
        if rc != 0:
            raise RuntimeError(f"scatter qsub failed: {err}")
        scatter_id = re.search(r"(\d+)", out).group(1)
        log.info("Scatter job submitted: %s", scatter_id)

        # Submit gather (held on scatter)
        gather_cmd = (
            f"qsub -hold_jid {scatter_id} -cwd -b y -V "
            f"python3 {script} "
            f"--bed {remote_bed} --cram-list {settings.hcluster_cram_list} "
            f"--tmp-dir {remote_tmp} --gather -o {remote_out}"
        )
        rc, out, err = _run(client, gather_cmd)
        if rc != 0:
            raise RuntimeError(f"gather qsub failed: {err}")
        gather_id = re.search(r"(\d+)", out).group(1)
        log.info("Gather job submitted: %s (held on %s)", gather_id, scatter_id)

        return gather_id, str(remote_out)

    finally:
        client.close()


def is_job_done(sge_job_id: str) -> bool:
    """Return True when the SGE job ID is no longer in the queue."""
    client = _get_client()
    try:
        rc, out, _ = _run(client, f"qstat -j {sge_job_id} 2>&1")
        return rc != 0  # qstat exits non-zero when job is not found
    finally:
        client.close()


def fetch_results(result_path: str) -> list[dict]:
    """Read the output TSV from scratch and return a list of row dicts."""
    client = _get_client()
    try:
        sftp = client.open_sftp()
        with sftp.open(result_path, "r") as fh:
            content = fh.read().decode()
        sftp.close()
    finally:
        client.close()

    rows = []
    reader = csv.DictReader(io.StringIO(content), delimiter="\t")
    for row in reader:
        rows.append({
            "gene": row["gene"],
            "n_samples": int(row["n_samples"]),
            "min_mean_cov": float(row["min_mean_cov"]),
            "max_mean_cov": float(row["max_mean_cov"]),
            "mean_mean_cov": float(row["mean_mean_cov"]),
            "min_pct_nx": float(row[next(k for k in row if k.startswith("min_pct_"))]),
            "mean_pct_nx": float(row[next(k for k in row if k.startswith("mean_pct_"))]),
            "threshold": settings.min_depth,
        })
    return rows


async def poll_until_done(sge_job_id: str) -> None:
    """Async loop that sleeps until the SGE job is no longer in queue."""
    while True:
        done = await asyncio.get_event_loop().run_in_executor(None, is_job_done, sge_job_id)
        if done:
            return
        await asyncio.sleep(_POLL_INTERVAL)
