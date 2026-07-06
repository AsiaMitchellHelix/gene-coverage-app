"""
POST /api/query

Accepts a list of identifiers (gene names, rsIDs, genomic coordinates) and a
user email address.  Returns:
  - cache_hits: list of GeneCoverage rows resolved immediately from the DB
  - job_id: UUID of the async Hcluster job for any cache misses (null if none)
  - unresolvable: identifiers that could not be mapped to any gene
"""

import asyncio
import logging
import os
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, EmailStr

from app.auth import require_user
from app.db.crud import create_job, get_gene_coverage, update_job, upsert_gene_coverage
from app.db.models import JobStatus
from app.db.session import get_db, AsyncSession
from app.services import annotation, hcluster, email as email_svc

log = logging.getLogger(__name__)
router = APIRouter()


class QueryRequest(BaseModel):
    identifiers: list[str]
    email: EmailStr


class CoverageRow(BaseModel):
    gene: str
    n_samples: int
    min_mean_cov: float
    max_mean_cov: float
    mean_mean_cov: float
    min_pct_nx: float
    mean_pct_nx: float
    threshold: int


class QueryResponse(BaseModel):
    cache_hits: list[CoverageRow]
    job_id: str | None
    unresolvable: list[str]


async def _run_hcluster_job(
    job_id,
    user_email: str,
    miss_genes: list[str],
    identifiers: list[str],
    db: AsyncSession,
) -> None:
    bed_path = None
    try:
        bed_path = annotation.genes_to_bed(miss_genes)

        sge_id, result_path = await asyncio.get_event_loop().run_in_executor(
            None, hcluster.submit_job, job_id, bed_path
        )
        await update_job(db, job_id, sge_job_id=sge_id, status=JobStatus.running,
                         result_path=result_path)

        await hcluster.poll_until_done(sge_id)

        rows = await asyncio.get_event_loop().run_in_executor(
            None, hcluster.fetch_results, result_path
        )

        await upsert_gene_coverage(db, rows)
        await update_job(db, job_id, status=JobStatus.done)

        await asyncio.get_event_loop().run_in_executor(
            None, email_svc.send_report, user_email, identifiers, rows
        )

    except Exception:
        log.exception("Hcluster job %s failed", job_id)
        await update_job(db, job_id, status=JobStatus.failed)
    finally:
        if bed_path and os.path.exists(bed_path):
            os.unlink(bed_path)


@router.post("/query", response_model=QueryResponse)
async def query(
    req: QueryRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[str, Depends(require_user)],
) -> QueryResponse:
    # Resolve all identifiers to gene names
    resolved = annotation.resolve_identifiers(req.identifiers)
    all_genes: set[str] = set()
    unresolvable: list[str] = []
    for ident, genes in resolved.items():
        if genes:
            all_genes.update(genes)
        else:
            unresolvable.append(ident)

    # Look up which genes have pre-computed metrics
    cached = await get_gene_coverage(db, list(all_genes))
    cached_genes = {row.gene for row in cached}
    miss_genes = sorted(all_genes - cached_genes)

    cache_hits = [
        CoverageRow(
            gene=row.gene,
            n_samples=row.n_samples,
            min_mean_cov=row.min_mean_cov,
            max_mean_cov=row.max_mean_cov,
            mean_mean_cov=row.mean_mean_cov,
            min_pct_nx=row.min_pct_nx,
            mean_pct_nx=row.mean_pct_nx,
            threshold=row.threshold,
        )
        for row in cached
    ]

    job_id = None
    if miss_genes:
        job = await create_job(db, req.email, req.identifiers)
        job_id = str(job.job_id)
        background_tasks.add_task(
            _run_hcluster_job, job.job_id, req.email, miss_genes, req.identifiers, db
        )

    return QueryResponse(cache_hits=cache_hits, job_id=job_id, unresolvable=unresolvable)
