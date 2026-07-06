from datetime import datetime
from typing import Sequence
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GeneCoverage, Job, JobStatus


async def get_gene_coverage(db: AsyncSession, genes: list[str]) -> list[GeneCoverage]:
    result = await db.execute(
        select(GeneCoverage).where(GeneCoverage.gene.in_(genes))
    )
    return list(result.scalars().all())


async def upsert_gene_coverage(db: AsyncSession, rows: list[dict]) -> None:
    stmt = insert(GeneCoverage).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["gene"],
        set_={c: stmt.excluded[c] for c in rows[0] if c != "gene"},
    )
    await db.execute(stmt)
    await db.commit()


async def create_job(db: AsyncSession, user_email: str, identifiers: list[str]) -> Job:
    job = Job(user_email=user_email, identifiers=identifiers)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def get_job(db: AsyncSession, job_id: UUID) -> Job | None:
    result = await db.execute(select(Job).where(Job.job_id == job_id))
    return result.scalar_one_or_none()


async def update_job(db: AsyncSession, job_id: UUID, **fields) -> None:
    await db.execute(update(Job).where(Job.job_id == job_id).values(**fields))
    await db.commit()
