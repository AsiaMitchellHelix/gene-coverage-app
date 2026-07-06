import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY, Column, DateTime, Enum, Float, Integer, String, Text, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class JobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class GeneCoverage(Base):
    __tablename__ = "gene_coverage"

    gene = Column(Text, primary_key=True)
    n_samples = Column(Integer, nullable=False)
    min_mean_cov = Column(Float, nullable=False)
    max_mean_cov = Column(Float, nullable=False)
    mean_mean_cov = Column(Float, nullable=False)
    min_pct_nx = Column(Float, nullable=False)
    mean_pct_nx = Column(Float, nullable=False)
    threshold = Column(Integer, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Job(Base):
    __tablename__ = "jobs"

    job_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_email = Column(Text, nullable=False)
    identifiers = Column(ARRAY(Text), nullable=False)
    sge_job_id = Column(Text)
    status = Column(Enum(JobStatus), nullable=False, default=JobStatus.pending)
    result_path = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime)
