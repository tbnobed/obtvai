from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
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
    KeywordHeatmapOut,
    KeywordHeatmapRowOut,
    InsightItemOut,
    InsightPersonRefOut,
    InsightTopicRefOut,
    StoryOpportunityOut,
    CoverageGapOut,
    TopPersonOut,
    TopTopicOut,
    ProcessingJobOut,
)
from ..topic_norm import normalize_topic_key, topic_label, group_topics

router = APIRouter(prefix="/insights", tags=["insights"])

# Diarization placeholders ("Person 3") that were never renamed.
PLACEHOLDER_NAME_SQL = r"^person \d+$"


def _person_refs(raw) -> list[InsightPersonRefOut]:
    out = []
    for p in raw if isinstance(raw, list) else []:
        if isinstance(p, dict) and p.get("display_name"):
            out.append(
                InsightPersonRefOut(
                    person_id=p.get("person_id") or None,
                    display_name=str(p["display_name"])[:200],
                )
            )
    return out


@router.get("/keyword-heatmap", response_model=KeywordHeatmapOut)
async def get_keyword_heatmap(
    months: int = Query(12, ge=3, le=36),
    limit: int = Query(20, ge=5, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Videos per keyword per month, bucketed by ingest date. Raw topic tags
    are merged by normalized key so casing/underscore variants count as one
    keyword — same convention as the /insights topic aggregates."""
    # Month axis: oldest first, ending at the current month, always dense so
    # the frontend can align counts index-for-index (empty months stay 0).
    now = datetime.utcnow()
    axis: list[str] = []
    y, m = now.year, now.month
    for _ in range(months):
        axis.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    axis.reverse()
    month_index = {ym: i for i, ym in enumerate(axis)}

    raw_rows = (
        await db.execute(
            text("""
                SELECT topic,
                       to_char(date_trunc('month', created_at), 'YYYY-MM') AS ym,
                       COUNT(DISTINCT id) AS n
                FROM media_assets, jsonb_array_elements_text(topics) AS topic
                WHERE topics IS NOT NULL
                  AND created_at >= date_trunc('month', now()) - make_interval(months => :back)
                GROUP BY topic, ym
            """),
            {"back": months - 1},
        )
    ).all()

    counts_by_key: dict[str, list[int]] = {}
    for topic, ym, n in raw_rows:
        key = normalize_topic_key(str(topic))
        idx = month_index.get(ym)
        if not key or idx is None:
            continue
        counts_by_key.setdefault(key, [0] * len(axis))[idx] += int(n)

    rows = [
        KeywordHeatmapRowOut(key=key, label=topic_label(key), total=sum(counts), counts=counts)
        for key, counts in counts_by_key.items()
    ]
    rows.sort(key=lambda r: r.total, reverse=True)
    return KeywordHeatmapOut(months=axis, rows=rows[:limit])


@router.get("", response_model=LibraryInsightsOut)
async def get_library_insights(db: AsyncSession = Depends(get_db)):
    total_assets, total_duration = (
        await db.execute(
            select(func.count(MediaAsset.id), func.coalesce(func.sum(MediaAsset.duration_seconds), 0))
        )
    ).one()
    total_people = (await db.execute(select(func.count(Person.id)))).scalar_one()
    unidentified_people = (
        await db.execute(
            select(func.count(Person.id)).where(
                Person.display_name.op("~*")(PLACEHOLDER_NAME_SQL)
            )
        )
    ).scalar_one()
    transcribed = (
        await db.execute(
            select(func.count(func.distinct(TranscriptSegment.media_id)))
        )
    ).scalar_one()
    # Duration of assets whose speech is searchable — same definition as
    # /media/stats/summary so the two pages always agree.
    speech_indexed = (
        await db.execute(
            select(func.coalesce(func.sum(MediaAsset.duration_seconds), 0)).where(
                MediaAsset.id.in_(select(func.distinct(TranscriptSegment.media_id)))
            )
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

    # Per-asset topic counts by raw string; DISTINCT inside each asset so a tag
    # repeated within one asset still counts that asset once. Grouped by
    # normalized key in Python so "Local AI Infrastructure" and
    # "local_ai_infrastructure" merge into a single topic.
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
    grouped_topics = group_topics((t, int(n)) for t, n in raw_topic_rows)
    counts_by_key = {g["key"]: g["asset_count"] for g in grouped_topics}

    stored = (
        await db.execute(select(LibraryInsight).where(LibraryInsight.id == 1))
    ).scalar_one_or_none()

    insight_items = []
    for i in (stored.insights or []) if stored else []:
        if not (isinstance(i, dict) and i.get("title") and i.get("detail")):
            continue
        topics_refs = [
            InsightTopicRefOut(key=normalize_topic_key(str(t.get("key") or t.get("label"))),
                               label=str(t.get("label") or topic_label(normalize_topic_key(str(t.get("key"))))))
            for t in (i.get("related_topics") or [])
            if isinstance(t, dict) and (t.get("key") or t.get("label"))
        ]
        insight_items.append(
            InsightItemOut(
                title=i["title"],
                detail=i["detail"],
                related_people=_person_refs(i.get("related_people")) or None,
                related_topics=topics_refs or None,
            )
        )

    opportunities = []
    for o in (stored.opportunities or []) if stored else []:
        if not (isinstance(o, dict) and o.get("title") and o.get("rationale")):
            continue
        asset_ids = [str(a) for a in (o.get("asset_ids") or []) if a]
        if not asset_ids:
            continue
        opportunities.append(
            StoryOpportunityOut(
                title=str(o["title"])[:300],
                rationale=str(o["rationale"])[:2000],
                asset_ids=asset_ids,
                people=_person_refs(o.get("people")),
                total_duration_seconds=float(o.get("total_duration_seconds") or 0),
            )
        )

    coverage_gaps = []
    for g in (stored.coverage_gaps or []) if stored else []:
        if not isinstance(g, dict):
            continue
        key = normalize_topic_key(str(g.get("key") or g.get("label") or ""))
        if not key:
            continue
        coverage_gaps.append(
            CoverageGapOut(
                key=key,
                label=str(g.get("label")) if g.get("label") else topic_label(key),
                # Count computed at read time so it stays honest as media lands.
                asset_count=counts_by_key.get(key, 0),
            )
        )

    return LibraryInsightsOut(
        generated_at=stored.generated_at if stored else None,
        headline=stored.headline if stored else None,
        insights=insight_items,
        opportunities=opportunities,
        coverage_gaps=coverage_gaps,
        stats=LibraryInsightsStatsOut(
            total_assets=int(total_assets or 0),
            total_duration_seconds=float(total_duration or 0),
            speech_indexed_seconds=float(speech_indexed or 0),
            total_people=int(total_people or 0),
            named_people_count=int(total_people or 0) - int(unidentified_people or 0),
            unidentified_people_count=int(unidentified_people or 0),
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
            TopTopicOut(key=g["key"], topic=g["topic"], asset_count=g["asset_count"])
            for g in grouped_topics[:15]
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
