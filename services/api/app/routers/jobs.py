from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, delete
from ..database import get_db
from ..models import ProcessingJob, MediaAsset
from ..schemas import ProcessingJobOut, JobCleanupIn, JobCleanupOut

router = APIRouter(prefix="/jobs", tags=["jobs"])

FINISHED_STATUSES = ("success", "error", "cancelled")


async def prune_finished_jobs(db: AsyncSession, media_id: str | None, job_type: str) -> None:
    """Delete finished jobs of the same (media_id, job_type) so re-runs replace
    their history instead of piling up duplicate rows. Does not commit."""
    q = delete(ProcessingJob).where(
        ProcessingJob.job_type == job_type,
        ProcessingJob.status.in_(FINISHED_STATUSES),
    )
    if media_id is None:
        q = q.where(ProcessingJob.media_id.is_(None))
    else:
        q = q.where(ProcessingJob.media_id == media_id)
    await db.execute(q)


def _enrich(job: ProcessingJob, asset: MediaAsset | None) -> ProcessingJobOut:
    out = ProcessingJobOut.model_validate(job)
    if asset:
        out.filename = asset.filename
    return out


@router.get("", response_model=list[ProcessingJobOut])
async def list_jobs(
    media_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(ProcessingJob, MediaAsset)
        .outerjoin(MediaAsset, ProcessingJob.media_id == MediaAsset.id)
        .order_by(desc(ProcessingJob.created_at))
    )
    if media_id:
        q = q.where(ProcessingJob.media_id == media_id)
    if status:
        q = q.where(ProcessingJob.status == status)
    q = q.limit(limit)
    rows = (await db.execute(q)).all()
    return [_enrich(job, asset) for job, asset in rows]


@router.post("/cleanup", response_model=JobCleanupOut)
async def cleanup_jobs(body: JobCleanupIn | None = None, db: AsyncSession = Depends(get_db)):
    statuses = tuple(body.statuses) if body and body.statuses else FINISHED_STATUSES
    invalid = [s for s in statuses if s not in FINISHED_STATUSES]
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=f"Only finished statuses can be cleaned up: {', '.join(FINISHED_STATUSES)}",
        )
    result = await db.execute(
        delete(ProcessingJob).where(ProcessingJob.status.in_(statuses))
    )
    await db.commit()
    return JobCleanupOut(deleted=result.rowcount or 0)


@router.get("/{id}", response_model=ProcessingJobOut)
async def get_job(id: str, db: AsyncSession = Depends(get_db)):
    row = (
        await db.execute(
            select(ProcessingJob, MediaAsset)
            .outerjoin(MediaAsset, ProcessingJob.media_id == MediaAsset.id)
            .where(ProcessingJob.id == id)
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    job, asset = row
    return _enrich(job, asset)


@router.post("/{id}/retry", response_model=ProcessingJobOut, status_code=202)
async def retry_job(id: str, db: AsyncSession = Depends(get_db)):
    row = (
        await db.execute(
            select(ProcessingJob, MediaAsset)
            .outerjoin(MediaAsset, ProcessingJob.media_id == MediaAsset.id)
            .where(ProcessingJob.id == id)
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    job, asset = row
    if job.status in ("running", "pending"):
        raise HTTPException(status_code=400, detail="Job is already queued or running")

    job.status = "pending"
    job.error_message = None
    job.retry_count += 1
    job.started_at = None
    job.finished_at = None
    await db.commit()
    await db.refresh(job)

    from ..worker_client import enqueue_job
    await enqueue_job(job.job_type, job.media_id, job.id)

    return _enrich(job, asset)


@router.post("/{id}/cancel", response_model=ProcessingJobOut)
async def cancel_job(id: str, db: AsyncSession = Depends(get_db)):
    row = (
        await db.execute(
            select(ProcessingJob, MediaAsset)
            .outerjoin(MediaAsset, ProcessingJob.media_id == MediaAsset.id)
            .where(ProcessingJob.id == id)
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    job, asset = row
    if job.status in ("success", "error"):
        raise HTTPException(status_code=400, detail="Completed jobs cannot be cancelled")

    if job.celery_task_id:
        try:
            from ..services.celery_app import celery_app
            celery_app.control.revoke(job.celery_task_id, terminate=True)
        except Exception:
            pass

    job.status = "cancelled"
    await db.commit()
    await db.refresh(job)
    return _enrich(job, asset)
