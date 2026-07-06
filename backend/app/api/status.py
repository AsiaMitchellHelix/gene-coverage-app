from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import require_user
from app.db.crud import get_job
from app.db.session import AsyncSession, get_db

router = APIRouter()


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    created_at: str
    completed_at: str | None


@router.get("/status/{job_id}", response_model=JobStatusResponse)
async def get_status(
    job_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[str, Depends(require_user)],
) -> JobStatusResponse:
    job = await get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatusResponse(
        job_id=str(job.job_id),
        status=job.status.value,
        created_at=job.created_at.isoformat(),
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
    )
