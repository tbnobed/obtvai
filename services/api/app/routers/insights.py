from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from ..database import get_db
from ..models import (
    Person,
    PersonAppearance,
    MediaAsset,
    LibraryInsight,
    ProcessingJob,
    TranscriptSegment,
)
from ..schemas import (
    LibraryInsightsOut,
    LibraryInsightsStatsOut,
    InsightItemOut,
    TopPersonOut,
    TopTopicOut,
    ProcessingJobOut,
)

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("", response_model=LibraryInsightsOut)
async def get_library_insights(db: AsyncSession = Depends(get_db)):
    total_assets, total_duration = (
        await db.execute(
            select(func.count(MediaAsset.id), func.coalesce(func.sum(MediaAsset.duration_seconds), 0))
        )
    ).one()
    total_people = (await db.execute(select(func.count(Person.id)))).scalar_one()
    transcribed = (
        await db.execute(
            select(func.count(func.distinct(TranscriptSegment.media_id)))
        )
    ).scalar_one()
    total_speaking = (
        await db.execute(
            select(func.coalesce(func.sum(PersonAppearance.speaking_seconds), 0))
        )
    ).scalar_one()

    top_people_rows = (
        await db.execute(
            select(
                Person.id,
                Person.display_name,
                Person.thumbnail_url,
                func.count(func.distinct(PersonAppearance.media_id)).label("assets"),
                func.coalesce(func.sum(PersonAppearance.speaking_seconds), 0).label("secs"),
            )
            .join(PersonAppearance, PersonAppearance.person_id == Person.id)
            .group_by(Person.id)
            .order_by(func.count(func.distinct(PersonAppearance.media_id)).desc())
            .limit(10)
        )
    ).all()

    top_topics_rows = (
        await db.execute(
            text("""
                SELECT topic, COUNT(*) AS n
                FROM media_assets, jsonb_array_elements_text(topics) AS topic
                WHERE topics IS NOT NULL
                GROUP BY topic
                ORDER BY n DESC
                LIMIT 15
            """)
        )
    ).all()

    stored = (
        await db.execute(select(LibraryInsight).where(LibraryInsight.id == 1))
    ).scalar_one_or_none()

    return LibraryInsightsOut(
        generated_at=stored.generated_at if stored else None,
        headline=stored.headline if stored else None,
        insights=[
            InsightItemOut(title=i["title"], detail=i["detail"])
            for i in (stored.insights or [])
            if isinstance(i, dict) and i.get("title") and i.get("detail")
        ]
        if stored
        else [],
        stats=LibraryInsightsStatsOut(
            total_assets=int(total_assets or 0),
            total_duration_seconds=float(total_duration or 0),
            total_people=int(total_people or 0),
            transcribed_assets=int(transcribed or 0),
            total_speaking_seconds=float(total_speaking or 0),
        ),
        top_people=[
            TopPersonOut(
                person_id=pid,
                display_name=name,
                thumbnail_url=thumb,
                asset_count=int(assets),
                speaking_seconds=float(secs or 0),
            )
            for pid, name, thumb, assets, secs in top_people_rows
        ],
        top_topics=[
            TopTopicOut(topic=t, asset_count=int(n)) for t, n in top_topics_rows
        ],
    )


@router.post("/refresh", response_model=ProcessingJobOut, status_code=202)
async def refresh_library_insights(db: AsyncSession = Depends(get_db)):
    existing = (
        await db.execute(
            select(ProcessingJob).where(
                ProcessingJob.job_type == "insights",
                ProcessingJob.status.in_(("pending", "running")),
            )
        )
    ).scalars().first()
    if existing:
        return ProcessingJobOut.model_validate(existing)

    from sqlalchemy.exc import IntegrityError

    from .jobs import prune_finished_jobs
    await prune_finished_jobs(db, None, "insights")
    job = ProcessingJob(media_id=None, job_type="insights", status="pending", logs=[])
    db.add(job)
    try:
        await db.commit()
    except IntegrityError:
        # Partial unique index: another request enqueued an insights job
        # concurrently — return that one instead of erroring.
        await db.rollback()
        existing = (
            await db.execute(
                select(ProcessingJob).where(
                    ProcessingJob.job_type == "insights",
                    ProcessingJob.status.in_(("pending", "running")),
                )
            )
        ).scalars().first()
        if existing:
            return ProcessingJobOut.model_validate(existing)
        raise HTTPException(status_code=409, detail="Insights refresh already in progress")
    await db.refresh(job)

    from ..worker_client import enqueue_job

    await enqueue_job("insights", None, job.id)
    return ProcessingJobOut.model_validate(job)
