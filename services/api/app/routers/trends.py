"""External trend correlation: YouTube trending + SearXNG news momentum.

Trend rows are fetched by the worker (tasks/trends.py) on a beat schedule or
via POST /trends/refresh. This router only reads them and correlates against
the library's own topics at read time, so counts stay accurate as the
library grows (same pattern as the insights coverage gaps).
"""
import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from ..database import get_db
from ..models import TrendTopic, ProcessingJob
from ..schemas import (
    TrendsOut,
    YoutubeTrendOut,
    WebTrendOut,
    TrendHeadlineOut,
    TrendMatchedTopicOut,
    ProcessingJobOut,
)
from ..topic_norm import group_topics

router = APIRouter(prefix="/trends", tags=["trends"])

MATCHED_TOPICS_CAP = 5


@router.get("", response_model=TrendsOut)
async def get_trends(db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(select(TrendTopic).order_by(TrendTopic.source, TrendTopic.rank))
    ).scalars().all()

    # Library topic counts, grouped by normalized key at read time.
    raw_topic_rows = (
        await db.execute(
            text("""
                SELECT topic, COUNT(DISTINCT id) AS n
                FROM media_assets, jsonb_array_elements_text(topics) AS topic
                WHERE topics IS NOT NULL
                GROUP BY topic
            """)
        )
    ).all()
    grouped = group_topics((t, int(n)) for t, n in raw_topic_rows)
    counts_by_key = {g["key"]: g["asset_count"] for g in grouped}
    labels_by_key = {g["key"]: g["topic"] for g in grouped}

    youtube: list[YoutubeTrendOut] = []
    web: list[WebTrendOut] = []
    fetched_at = None

    for r in rows:
        if fetched_at is None or (r.fetched_at and r.fetched_at > fetched_at):
            fetched_at = r.fetched_at
        meta = r.meta or {}
        if r.source == "youtube":
            # Token-boundary match: library topic key must appear as a whole
            # token sequence inside the normalized title+tags haystack.
            haystack = f" {meta.get('haystack') or ''} "
            matched = [
                TrendMatchedTopicOut(
                    key=key, topic=labels_by_key[key], asset_count=counts_by_key[key]
                )
                for key in counts_by_key
                if f" {key} " in haystack
            ]
            matched.sort(key=lambda m: -m.asset_count)
            youtube.append(
                YoutubeTrendOut(
                    rank=r.rank or 0,
                    title=r.label,
                    channel=meta.get("channel"),
                    url=meta.get("url"),
                    views=meta.get("views"),
                    matched_topics=matched[:MATCHED_TOPICS_CAP],
                )
            )
        elif r.source == "web":
            key = r.topic_key or ""
            web.append(
                WebTrendOut(
                    rank=r.rank or 0,
                    key=key,
                    topic=labels_by_key.get(key, r.label),
                    asset_count=counts_by_key.get(key, 0),
                    result_count=int(r.score or 0),
                    headlines=[
                        TrendHeadlineOut(title=h.get("title") or "", url=h.get("url"))
                        for h in (meta.get("headlines") or [])
                        if isinstance(h, dict)
                    ],
                )
            )

    # Web panel: most news activity first.
    web.sort(key=lambda w: (-w.result_count, w.rank))

    return TrendsOut(
        fetched_at=fetched_at,
        youtube_configured=bool(
            os.getenv("YOUTUBE_API_KEY")
            or (os.getenv("YOUTUBE_CLIENT_ID") and os.getenv("YOUTUBE_REFRESH_TOKEN"))
        ),
        web_configured=bool(os.getenv("SEARXNG_URL")),
        youtube=youtube,
        web=web,
    )


@router.post("/refresh", response_model=ProcessingJobOut, status_code=202)
async def refresh_trends(db: AsyncSession = Depends(get_db)):
    existing = (
        await db.execute(
            select(ProcessingJob).where(
                ProcessingJob.job_type == "trends",
                ProcessingJob.status.in_(("pending", "running")),
            )
        )
    ).scalars().first()
    if existing:
        return ProcessingJobOut.model_validate(existing)

    from sqlalchemy.exc import IntegrityError

    from .jobs import prune_finished_jobs
    await prune_finished_jobs(db, None, "trends")
    job = ProcessingJob(media_id=None, job_type="trends", status="pending", logs=[])
    db.add(job)
    try:
        await db.commit()
    except IntegrityError:
        # Partial unique index: another request enqueued a trends job
        # concurrently — return that one instead of erroring.
        await db.rollback()
        existing = (
            await db.execute(
                select(ProcessingJob).where(
                    ProcessingJob.job_type == "trends",
                    ProcessingJob.status.in_(("pending", "running")),
                )
            )
        ).scalars().first()
        if existing:
            return ProcessingJobOut.model_validate(existing)
        raise HTTPException(status_code=409, detail="Trends refresh already in progress")
    await db.refresh(job)

    from ..worker_client import enqueue_job

    await enqueue_job("trends", None, job.id)
    return ProcessingJobOut.model_validate(job)
