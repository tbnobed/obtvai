from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, delete, func
from ..database import get_db
from ..models import ProcessingJob, MediaAsset
from ..schemas import ProcessingJobOut, JobCleanupIn, JobCleanupOut, JobStatsOut, JobStageStatsOut, RetryFailedOut

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


@router.get("/stats", response_model=JobStatsOut)
async def get_job_stats(db: AsyncSession = Depends(get_db)):
    asset_status_q = await db.execute(
        select(MediaAsset.status, func.count(MediaAsset.id)).group_by(MediaAsset.status)
    )
    asset_counts = {row[0]: row[1] for row in asset_status_q.all()}
    assets_total = sum(asset_counts.values())
    assets_ready = asset_counts.get("ready", 0)
    assets_error = asset_counts.get("error", 0)
    assets_processing = assets_total - assets_ready - assets_error

    stage_q = await db.execute(
        select(ProcessingJob.job_type, ProcessingJob.status, func.count(ProcessingJob.id))
        .group_by(ProcessingJob.job_type, ProcessingJob.status)
    )
    stages: dict[str, dict[str, int]] = {}
    for job_type, status, count in stage_q.all():
        stages.setdefault(job_type, {"pending": 0, "running": 0, "success": 0, "error": 0})
        if status in stages[job_type]:
            stages[job_type][status] += count

    totals = {"pending": 0, "running": 0, "error": 0}
    for counts in stages.values():
        for k in totals:
            totals[k] += counts[k]

    return JobStatsOut(
        assets_total=assets_total,
        assets_ready=assets_ready,
        assets_processing=assets_processing,
        assets_error=assets_error,
        jobs_pending=totals["pending"],
        jobs_running=totals["running"],
        jobs_error=totals["error"],
        stages=[
            JobStageStatsOut(job_type=jt, **counts)
            for jt, counts in sorted(stages.items())
        ],
    )


def _legacy_params_from_logs(job_type: str, params: dict | None, logs: list | None) -> dict | None:
    """Jobs created before the params column have NULL params; dub/translate
    tasks need target_language, which their creation log line records. Derive
    it so old failed jobs remain retryable."""
    if params:
        return params
    if job_type in ("dub", "translate"):
        for line in logs or []:
            if isinstance(line, str) and line.startswith("Target language: "):
                return {"target_language": line[len("Target language: "):].strip()}
    return None


@router.post("/retry-failed", response_model=RetryFailedOut, status_code=202)
async def retry_failed_jobs(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import update

    # Atomically claim the failed jobs (concurrent calls each claim a disjoint
    # set) so the same job is never double-enqueued.
    claimed = (
        await db.execute(
            update(ProcessingJob)
            .where(ProcessingJob.status == "error")
            .values(
                status="pending",
                error_message=None,
                retry_count=ProcessingJob.retry_count + 1,
                started_at=None,
                finished_at=None,
            )
            .returning(ProcessingJob.id, ProcessingJob.job_type, ProcessingJob.media_id, ProcessingJob.params, ProcessingJob.logs)
        )
    ).all()
    await db.commit()

    from ..worker_client import enqueue_job
    retried = 0
    for job_id, job_type, media_id, params, logs in claimed:
        try:
            await enqueue_job(job_type, media_id, job_id, extra=_legacy_params_from_logs(job_type, params, logs))
            retried += 1
        except Exception as e:
            # Never strand a claimed job as pending-but-unqueued: put it back
            # into error state so a later retry can pick it up.
            await db.execute(
                update(ProcessingJob)
                .where(ProcessingJob.id == job_id)
                .values(status="error", error_message=f"re-queue failed: {e}")
            )
            await db.commit()

    return RetryFailedOut(retried=retried)


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
    await enqueue_job(job.job_type, job.media_id, job.id, extra=_legacy_params_from_logs(job.job_type, job.params, job.logs))

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
