"""Social media performance: programs, channels, snapshots, posts.

Channel/post metrics are fetched by the worker (tasks/social_sync.py) on a
beat schedule or via POST /socials/refresh. This router manages the
program/channel registry and reads stored metrics; week-over-week deltas are
computed at read time from snapshots.
"""
import asyncio
import math
import os
from datetime import datetime, timedelta
from numbers import Real

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func

from ..database import get_db, AsyncSessionLocal
from ..models import (
    SocialProgram,
    SocialChannel,
    SocialChannelSnapshot,
    SocialPost,
    ProcessingJob,
)
from ..schemas import (
    SocialProgramIn,
    SocialProgramOut,
    SocialChannelIn,
    SocialChannelUpdateIn,
    SocialChannelOut,
    SocialChannelOverviewOut,
    SocialProgramOverviewOut,
    SocialSnapshotOut,
    SocialPostOut,
    SocialsOverviewOut,
    SocialsInsightsOut,
    SocialChannelAnalysisOut,
    ProcessingJobOut,
)

router = APIRouter(prefix="/socials", tags=["socials"])


def _snap_out(s: SocialChannelSnapshot | None) -> SocialSnapshotOut | None:
    if s is None:
        return None
    return SocialSnapshotOut(
        fetched_at=s.fetched_at,
        followers=s.followers,
        total_views=s.total_views,
        posts_count=s.posts_count,
    )


@router.get("", response_model=SocialsOverviewOut)
async def get_socials_overview(db: AsyncSession = Depends(get_db)):
    programs = (
        await db.execute(select(SocialProgram).order_by(SocialProgram.created_at))
    ).scalars().all()
    channels = (
        await db.execute(select(SocialChannel).order_by(SocialChannel.created_at))
    ).scalars().all()

    week_ago_ts = datetime.utcnow() - timedelta(days=7)
    latest_by_channel: dict[str, SocialChannelSnapshot] = {}
    week_by_channel: dict[str, SocialChannelSnapshot] = {}
    if channels:
        snaps = (
            await db.execute(
                select(SocialChannelSnapshot)
                .where(SocialChannelSnapshot.channel_id.in_([c.id for c in channels]))
                .order_by(SocialChannelSnapshot.fetched_at)
            )
        ).scalars().all()
        for s in snaps:
            latest_by_channel[s.channel_id] = s
            # Closest snapshot at-or-before 7 days ago; ordered scan keeps the last one.
            if s.fetched_at <= week_ago_ts:
                week_by_channel[s.channel_id] = s

    thumb_by_channel: dict[str, str] = {}
    if channels:
        posts = (
            await db.execute(
                select(SocialPost.channel_id, SocialPost.thumbnail_url)
                .where(
                    SocialPost.channel_id.in_([c.id for c in channels]),
                    SocialPost.thumbnail_url.is_not(None),
                )
                .order_by(SocialPost.published_at)
            )
        ).all()
        # Ordered scan — the last write per channel is the most recent post.
        for channel_id, thumbnail_url in posts:
            thumb_by_channel[channel_id] = thumbnail_url

    def channel_overview(c: SocialChannel) -> SocialChannelOverviewOut:
        return SocialChannelOverviewOut(
            id=c.id,
            program_id=c.program_id,
            platform=c.platform,
            handle=c.handle,
            url=c.url,
            external_id=c.external_id,
            display_name=c.display_name,
            avatar_url=c.avatar_url,
            last_sync_at=c.last_sync_at,
            last_error=c.last_error,
            created_at=c.created_at,
            latest=_snap_out(latest_by_channel.get(c.id)),
            week_ago=_snap_out(week_by_channel.get(c.id)),
            latest_post_thumbnail=thumb_by_channel.get(c.id),
        )

    last_synced = max(
        (c.last_sync_at for c in channels if c.last_sync_at is not None),
        default=None,
    )
    return SocialsOverviewOut(
        programs=[
            SocialProgramOverviewOut(
                id=p.id,
                name=p.name,
                created_at=p.created_at,
                channels=[channel_overview(c) for c in channels if c.program_id == p.id],
            )
            for p in programs
        ],
        last_synced_at=last_synced,
        youtube_configured=bool(os.getenv("YOUTUBE_API_KEY")),
        meta_configured=bool(os.getenv("META_ACCESS_TOKEN")),
        tiktok_configured=bool(os.getenv("TIKTOK_ACCESS_TOKEN")),
    )


@router.post("/programs", response_model=SocialProgramOut, status_code=201)
async def create_program(payload: SocialProgramIn, db: AsyncSession = Depends(get_db)):
    p = SocialProgram(name=payload.name.strip())
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return SocialProgramOut.model_validate(p, from_attributes=True)


@router.patch("/programs/{program_id}", response_model=SocialProgramOut)
async def update_program(
    program_id: str, payload: SocialProgramIn, db: AsyncSession = Depends(get_db)
):
    p = await db.get(SocialProgram, program_id)
    if not p:
        raise HTTPException(status_code=404, detail="Program not found")
    p.name = payload.name.strip()
    await db.commit()
    await db.refresh(p)
    return SocialProgramOut.model_validate(p, from_attributes=True)


@router.delete("/programs/{program_id}", status_code=204)
async def delete_program(program_id: str, db: AsyncSession = Depends(get_db)):
    p = await db.get(SocialProgram, program_id)
    if not p:
        raise HTTPException(status_code=404, detail="Program not found")
    await db.delete(p)
    await db.commit()


@router.post("/channels", response_model=SocialChannelOut, status_code=201)
async def create_channel(payload: SocialChannelIn, db: AsyncSession = Depends(get_db)):
    if not await db.get(SocialProgram, payload.program_id):
        raise HTTPException(status_code=404, detail="Program not found")
    c = SocialChannel(
        program_id=payload.program_id,
        platform=payload.platform,
        handle=payload.handle.strip(),
        url=payload.url,
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return SocialChannelOut.model_validate(c, from_attributes=True)


@router.patch("/channels/{channel_id}", response_model=SocialChannelOut)
async def update_channel(
    channel_id: str, payload: SocialChannelUpdateIn, db: AsyncSession = Depends(get_db)
):
    c = await db.get(SocialChannel, channel_id)
    if not c:
        raise HTTPException(status_code=404, detail="Channel not found")
    if payload.handle is not None:
        new_handle = payload.handle.strip()
        if new_handle and new_handle != c.handle:
            c.handle = new_handle
            # Handle changed: cached identity must be re-resolved on next sync.
            c.external_id = None
            c.display_name = None
            c.avatar_url = None
            c.last_error = None
    if "url" in payload.model_fields_set:
        c.url = payload.url
    await db.commit()
    await db.refresh(c)
    return SocialChannelOut.model_validate(c, from_attributes=True)


@router.delete("/channels/{channel_id}", status_code=204)
async def delete_channel(channel_id: str, db: AsyncSession = Depends(get_db)):
    c = await db.get(SocialChannel, channel_id)
    if not c:
        raise HTTPException(status_code=404, detail="Channel not found")
    await db.delete(c)
    await db.commit()


@router.get("/channels/{channel_id}/history", response_model=list[SocialSnapshotOut])
async def get_channel_history(
    channel_id: str, days: int = 90, db: AsyncSession = Depends(get_db)
):
    if not await db.get(SocialChannel, channel_id):
        raise HTTPException(status_code=404, detail="Channel not found")
    cutoff = datetime.utcnow() - timedelta(days=max(1, days))
    snaps = (
        await db.execute(
            select(SocialChannelSnapshot)
            .where(
                SocialChannelSnapshot.channel_id == channel_id,
                SocialChannelSnapshot.fetched_at >= cutoff,
            )
            .order_by(SocialChannelSnapshot.fetched_at)
        )
    ).scalars().all()
    return [_snap_out(s) for s in snaps]


@router.get("/channels/{channel_id}/posts", response_model=list[SocialPostOut])
async def list_channel_posts(
    channel_id: str, limit: int = 25, db: AsyncSession = Depends(get_db)
):
    if not await db.get(SocialChannel, channel_id):
        raise HTTPException(status_code=404, detail="Channel not found")
    posts = (
        await db.execute(
            select(SocialPost)
            .where(SocialPost.channel_id == channel_id)
            .order_by(SocialPost.published_at.desc().nulls_last())
            .limit(max(1, min(limit, 100)))
        )
    ).scalars().all()
    return [SocialPostOut.model_validate(p, from_attributes=True) for p in posts]


@router.post("/refresh", response_model=ProcessingJobOut, status_code=202)
async def refresh_socials(db: AsyncSession = Depends(get_db)):
    existing = (
        await db.execute(
            select(ProcessingJob).where(
                ProcessingJob.job_type == "social_sync",
                ProcessingJob.status.in_(("pending", "running")),
            )
        )
    ).scalars().first()
    if existing:
        return ProcessingJobOut.model_validate(existing)

    from sqlalchemy.exc import IntegrityError

    from .jobs import prune_finished_jobs
    await prune_finished_jobs(db, None, "social_sync")
    job = ProcessingJob(media_id=None, job_type="social_sync", status="pending", logs=[])
    db.add(job)
    try:
        await db.commit()
    except IntegrityError:
        # Partial unique index: another request enqueued a sync concurrently.
        await db.rollback()
        existing = (
            await db.execute(
                select(ProcessingJob).where(
                    ProcessingJob.job_type == "social_sync",
                    ProcessingJob.status.in_(("pending", "running")),
                )
            )
        ).scalars().first()
        if existing:
            return ProcessingJobOut.model_validate(existing)
        raise HTTPException(status_code=409, detail="Social sync already in progress")
    await db.refresh(job)

    from ..worker_client import enqueue_job

    await enqueue_job("social_sync", None, job.id)
    return ProcessingJobOut.model_validate(job)


# ── AI insights ───────────────────────────────────────────────────────────────

def _pct(now: int | None, before: int | None) -> float | None:
    if now is None or not before:
        return None
    return (now - before) / before * 100


async def _collect_metrics_summary(db: AsyncSession) -> tuple[str, dict] | None:
    """Compact per-channel metrics digest for the LLM, plus raw stats for the
    heuristic fallback."""
    programs = (
        await db.execute(select(SocialProgram).order_by(SocialProgram.created_at))
    ).scalars().all()
    channels = (
        await db.execute(select(SocialChannel).order_by(SocialChannel.created_at))
    ).scalars().all()
    if not channels:
        return None

    configured = {
        "youtube": bool(os.getenv("YOUTUBE_API_KEY")),
        "instagram": bool(os.getenv("META_ACCESS_TOKEN")),
        "facebook": bool(os.getenv("META_ACCESS_TOKEN")),
        "tiktok": bool(os.getenv("TIKTOK_ACCESS_TOKEN")),
    }

    prog_name = {p.id: p.name for p in programs}
    week_ago_ts = datetime.utcnow() - timedelta(days=7)
    lines: list[str] = []
    stats: dict = {"channels": []}

    for c in channels:
        # Channels on platforms without API credentials have no data — that's a
        # setup issue (already surfaced in the UI banner), not a content problem.
        if not configured.get(c.platform, True):
            continue
        snaps = (
            await db.execute(
                select(SocialChannelSnapshot)
                .where(SocialChannelSnapshot.channel_id == c.id)
                .order_by(SocialChannelSnapshot.fetched_at)
            )
        ).scalars().all()
        latest = snaps[-1] if snaps else None
        week = None
        for s in snaps:
            if s.fetched_at <= week_ago_ts:
                week = s
        growth = _pct(latest.followers if latest else None,
                      week.followers if week else None)

        posts = (
            await db.execute(
                select(SocialPost)
                .where(SocialPost.channel_id == c.id)
                .order_by(SocialPost.published_at.desc().nulls_last())
                .limit(20)
            )
        ).scalars().all()
        viewed = [p for p in posts if p.views is not None]
        avg_views = sum(p.views for p in viewed) / len(viewed) if viewed else None
        top = max(viewed, key=lambda p: p.views) if viewed else None
        bottom = min(viewed, key=lambda p: p.views) if viewed else None
        eng = None
        if viewed:
            pairs = [(p.likes or 0) + (p.comments or 0) for p in viewed]
            total_v = sum(p.views for p in viewed)
            eng = sum(pairs) / total_v * 100 if total_v else None

        name = f"{prog_name.get(c.program_id, '?')} / {c.platform} {c.handle}"
        parts = [f"{name}:"]
        if latest:
            parts.append(f"{latest.followers or 0} followers")
        if growth is not None:
            parts.append(f"{growth:+.1f}% followers this week")
        if avg_views is not None:
            parts.append(f"avg {avg_views:.0f} views/post (last {len(viewed)})")
        if eng is not None:
            parts.append(f"{eng:.1f}% engagement (likes+comments per view)")
        has_data = latest is not None or bool(viewed)
        if not has_data:
            # Nothing fetched yet (e.g. first sync pending or failing) —
            # no basis for content analysis.
            continue

        now = datetime.utcnow()
        dated = [p for p in posts if p.published_at is not None]
        recent_14d = [p for p in dated if (now - p.published_at).days <= 14]
        if dated:
            newest_age = (now - max(p.published_at for p in dated)).days
            parts.append(f"{len(recent_14d)} posts in last 14 days, newest {newest_age}d ago")
        if c.last_error:
            parts.append(f"SYNC ERROR: {c.last_error[:120]}")
        lines.append(" ".join(parts))
        for p in viewed[:15]:
            age = f"{(now - p.published_at).days}d ago" if p.published_at else "undated"
            lines.append(
                f'  - {p.views}v {p.likes or 0}l {p.comments or 0}c {age}: '
                f'"{(p.title or p.external_id)[:90]}"'
            )
        stats["channels"].append({
            "name": name, "growth": growth, "avg_views": avg_views,
            "engagement": eng, "top": top, "bottom": bottom, "error": c.last_error,
        })

    if not lines:
        return None
    return "\n".join(lines), stats


def _heuristic_insights(stats: dict) -> tuple[list[str], list[str], list[str]]:
    """Deterministic analysis used when the LLM is unavailable."""
    working: list[str] = []
    not_working: list[str] = []
    recs: list[str] = []
    chans = stats["channels"]
    for ch in chans:
        if ch["growth"] is not None and ch["growth"] >= 1.0:
            working.append(f"{ch['name']} is growing {ch['growth']:+.1f}% in followers this week.")
        elif ch["growth"] is not None and ch["growth"] < 0:
            not_working.append(f"{ch['name']} lost followers this week ({ch['growth']:+.1f}%).")
        if ch["engagement"] is not None and ch["engagement"] >= 6:
            working.append(f"{ch['name']} has strong engagement ({ch['engagement']:.1f}% likes+comments per view).")
        elif ch["engagement"] is not None and ch["engagement"] < 2:
            not_working.append(f"{ch['name']} engagement is low ({ch['engagement']:.1f}%) — views aren't converting to interactions.")
        if ch["top"] is not None and ch["bottom"] is not None and ch["bottom"].views:
            ratio = (ch["top"].views or 0) / ch["bottom"].views
            if ratio >= 3:
                working.append(f'"{(ch["top"].title or "")[:70]}" is a breakout on {ch["name"]} ({ch["top"].views} views, {ratio:.0f}x the weakest post).')
                recs.append(f'Make more content like "{(ch["top"].title or "")[:70]}" — it clearly outperforms on {ch["name"]}.')
        if ch["error"]:
            not_working.append(f"{ch['name']} is not syncing: {ch['error'][:120]}")
            recs.append(f"Fix the sync credentials for {ch['name']} so its metrics stay current.")
    if not recs and chans:
        recs.append("Keep the posting cadence steady and compare next week's deltas to spot trends.")
    return working[:6], not_working[:6], recs[:5]


def _parse_insight_lines(text: str) -> tuple[list[str], list[str], list[str]]:
    working: list[str] = []
    not_working: list[str] = []
    recs: list[str] = []
    for raw in text.splitlines():
        # Tolerate bullets and markdown bold around the labels ("**WORKING:**",
        # "- WORKING:") — larger models format more liberally.
        line = raw.strip().lstrip("-•* ").replace("**", "").strip()
        upper = line.upper()
        if upper.startswith("WORKING:"):
            working.append(line[len("WORKING:"):].strip())
        elif upper.startswith("NOT WORKING:"):
            not_working.append(line[len("NOT WORKING:"):].strip())
        elif upper.startswith("RECOMMEND:"):
            recs.append(line[len("RECOMMEND:"):].strip())
    return working[:6], not_working[:6], recs[:5]


# Async insight generation state. The LLM can take minutes on a remote 32B
# model, far longer than the proxy chain (edge openresty + nginx) will hold a
# request open — so the endpoint starts a background task and the client polls
# by re-POSTing until status is "ready". Single-process state is fine: the API
# runs as one uvicorn process.
_insights_task: "asyncio.Task | None" = None
_insights_result: "SocialsInsightsOut | None" = None
_insights_lock = asyncio.Lock()
_INSIGHTS_CACHE_SECONDS = 180


async def _generate_insights_now(summary: str, stats: dict) -> SocialsInsightsOut:
    prompt = (
        "You are a senior social media strategist for a TV broadcaster. Below are "
        "metrics for the station's social channels, grouped by program. Each channel "
        "line is followed by its recent posts (views v, likes l, comments c, age):\n\n"
        f"{summary}\n\n"
        "Find NON-OBVIOUS patterns a producer could act on. Specifically look for:\n"
        "- content themes/formats/guests that recur in the titles of high performers "
        "vs low performers (e.g. interviews vs full episodes vs highlight clips)\n"
        "- the same content performing differently across platforms, and why\n"
        "- engagement quality vs raw reach (a post with fewer views but far more "
        "likes/comments per view matters)\n"
        "- posting cadence problems (gaps, too infrequent, stale channels)\n"
        "- follower growth vs content output mismatches\n\n"
        "Rules: every line MUST cite concrete numbers AND draw a conclusion — never "
        "just restate a stat. Never mention a stat without saying what to do about "
        "it or why it happened. Compare at least two things in each observation. "
        "Base everything strictly on the data above — do not invent data. "
        "Recommendations must be concrete enough to act on this week (what to post, "
        "where, how often).\n\n"
        "Answer ONLY with lines in exactly this format (3-6 of each):\n"
        "WORKING: <one specific pattern-level observation with numbers>\n"
        "NOT WORKING: <one specific pattern-level observation with numbers>\n"
        "RECOMMEND: <one concrete action for this week>"
    )

    model_used = False
    working: list[str] = []
    not_working: list[str] = []
    recs: list[str] = []
    try:
        from ..services.llm import generate_response
        answer = await generate_response(prompt, max_new_tokens=1200)
        working, not_working, recs = _parse_insight_lines(answer)
        model_used = bool(working or not_working or recs)
        if not model_used:
            print(
                "Socials insights: LLM answered but no WORKING/NOT WORKING/"
                "RECOMMEND lines parsed"
            )
    except Exception as e:
        print(f"Socials insights: LLM generation failed: {type(e).__name__}")
    if not model_used:
        working, not_working, recs = _heuristic_insights(stats)

    return SocialsInsightsOut(
        status="ready",
        generated_at=datetime.utcnow(),
        working=working,
        not_working=not_working,
        recommendations=recs,
        model_used=model_used,
    )


async def _insights_background() -> None:
    """Run insight generation with its own DB session and store the result."""
    global _insights_result
    async with AsyncSessionLocal() as session:
        collected = await _collect_metrics_summary(session)
    if collected is None:
        # No data — surface as a heuristic-style empty result so the poll ends.
        _insights_result = SocialsInsightsOut(
            status="ready",
            generated_at=datetime.utcnow(),
            working=[],
            not_working=["No social channel data to analyze yet."],
            recommendations=[],
            model_used=False,
        )
        return
    summary, stats = collected
    _insights_result = await _generate_insights_now(summary, stats)
    await _save_insights(_insights_result)


async def _save_insights(result: "SocialsInsightsOut") -> None:
    """Persist a finished run so insights survive restarts and page loads."""
    from ..models import SocialInsight
    # Insert and prune are separate transactions: a prune failure must never
    # cost us the freshly generated result.
    try:
        async with AsyncSessionLocal() as db:
            db.add(SocialInsight(
                generated_at=result.generated_at,
                working=result.working,
                not_working=result.not_working,
                recommendations=result.recommendations,
                model_used=result.model_used,
            ))
            await db.commit()
    except Exception as e:
        print(f"Socials insights: failed to persist result: {type(e).__name__}")
        return
    try:
        async with AsyncSessionLocal() as db:
            # Keep a short history; prune everything but the newest 20 runs.
            from sqlalchemy import delete as sa_delete
            keep = select(SocialInsight.id).order_by(
                SocialInsight.generated_at.desc()).limit(20)
            await db.execute(sa_delete(SocialInsight).where(
                SocialInsight.id.notin_(keep.subquery().select())))
            await db.commit()
    except Exception as e:
        print(f"Socials insights: history prune failed (non-fatal): {type(e).__name__}")


@router.get("/insights", response_model=SocialsInsightsOut)
async def get_socials_insights(db: AsyncSession = Depends(get_db)):
    """Last saved insights run (survives restarts). 404 if never run."""
    from ..models import SocialInsight
    row = (await db.execute(
        select(SocialInsight).order_by(SocialInsight.generated_at.desc()).limit(1)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="No insights generated yet")
    return SocialsInsightsOut(
        status="ready",
        generated_at=row.generated_at,
        working=row.working or [],
        not_working=row.not_working or [],
        recommendations=row.recommendations or [],
        model_used=row.model_used,
    )


# ── Per-channel n8n analysis ─────────────────────────────────────────────────
# POSTs {channelId} to the n8n analyze-channel webhook and stores the parsed
# result. n8n can take a while, so the call runs in a background task and the
# client polls GET /channels/{id}/analysis until status != "running".

N8N_ANALYZE_URL = os.environ.get(
    "N8N_ANALYZE_URL", "https://n8n.obtv.io/webhook/analyze-channel")
_analysis_tasks: dict[str, asyncio.Task] = {}
_analysis_lock = asyncio.Lock()  # serializes analyze-start across channels
_MAX_ANALYSIS_HISTORY = 90
_MAX_N8N_RESPONSE_BYTES = 2 * 1024 * 1024


class _N8NEmptyResponseError(ValueError):
    """The webhook returned no JSON object."""


class _N8NMalformedResponseError(ValueError):
    """The webhook returned JSON with an invalid top-level shape."""


class _N8NHTTPStatusError(ValueError):
    """A non-success HTTP status without a valid v2 error envelope."""

    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"n8n returned HTTP {status_code}")


def _analysis_out(a) -> SocialChannelAnalysisOut:
    # Rows created before v2 have no analysis_version.  Mark successful legacy
    # rows explicitly so the UI can show a re-analyze notice instead of
    # presenting the old economics/projection narrative as current data.
    version = a.analysis_version
    legacy = version == 1 or (version is None and a.status == "ready")
    if legacy:
        version = 1
    warnings = list(a.data_warnings or [])
    if legacy and not any("Legacy analysis report" in warning for warning in warnings):
        warnings.append("Legacy analysis report; re-run analysis for v2 measured metrics.")
    return SocialChannelAnalysisOut(
        channel_id=a.channel_id,
        status=a.status,
        error=a.error,
        analyzed_at=a.analyzed_at,
        analysis_version=version,
        analysis_metrics=a.analysis_metrics,
        data_warnings=warnings,
        subs3=a.subs3,
        subs6=a.subs6,
        subs12=a.subs12,
        ai_summary=a.ai_summary,
        ai_recommendations=a.ai_recommendations or [],
        est_monthly_revenue=a.est_monthly_revenue or 0,
        margin_percent=a.margin_percent or 0,
        risk_level=a.risk_level or "unknown",
        top_videos=a.top_videos or [],
        ai_sections=a.ai_sections or [],
        avg_views=a.avg_views,
        avg_likes=a.avg_likes,
        avg_comments=a.avg_comments,
        engagement_rate=a.engagement_rate,
    )


_V2_METRIC_FIELDS = (
    "subscriber_count",
    "total_views",
    "total_videos",
    "sample_size",
    "avg_views",
    "median_views",
    "avg_likes",
    "avg_comments",
    "engagement_rate",
    "uploads_last_30d",
    "uploads_per_week",
    "recent_median_views",
    "previous_median_views",
    "performance_change_percent",
    "subscriber_change",
    "subscriber_change_percent",
    "history_days",
)
_V2_METRIC_INTEGERS = {
    "subscriber_count",
    "total_views",
    "total_videos",
    "sample_size",
    "uploads_last_30d",
    "subscriber_change",
}
_V2_METRIC_NONNEGATIVE = set(_V2_METRIC_FIELDS) - {
    "performance_change_percent",
    "subscriber_change",
    "subscriber_change_percent",
}
_V2_METRIC_DATES = ("observed_at", "sample_oldest_at", "sample_newest_at")


def _validated_metric(name: str, value):
    """Validate one v2 metric without converting unavailable data to zero."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"n8n metrics.{name} must be a finite number or null")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"n8n metrics.{name} must be a finite number or null")
    if name in _V2_METRIC_NONNEGATIVE and number < 0:
        raise ValueError(f"n8n metrics.{name} cannot be negative")
    if name in _V2_METRIC_INTEGERS:
        if not number.is_integer():
            raise ValueError(f"n8n metrics.{name} must be an integer or null")
        return int(number)
    return number


def _parse_top_videos(data: dict) -> list[dict]:
    """Validate the bounded v2 topVideos sample.

    These are videos from the recent sampled uploads, not an all-time
    leaderboard.  Do not manufacture zero counts when YouTube did not expose a
    measurement.
    """
    raw = data.get("topVideos")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("n8n topVideos must be an array")
    if len(raw) > 50:
        raise ValueError("n8n topVideos exceeds the 50-video sample limit")

    def count(item: dict, name: str) -> int | None:
        value = item.get(name)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError(f"n8n topVideos.{name} must be a finite number or null")
        if float(value) < 0 or not math.isfinite(float(value)):
            raise ValueError(f"n8n topVideos.{name} must be a finite non-negative number or null")
        validated = _validated_metric(f"topVideos.{name}", value)
        if validated is not None and not isinstance(validated, int):
            if not float(validated).is_integer():
                raise ValueError(f"n8n topVideos.{name} must be an integer or null")
            validated = int(validated)
        return validated

    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("n8n topVideos items must be objects")
        video_id = item.get("id")
        title = item.get("title")
        if not isinstance(video_id, str) or not video_id.strip():
            raise ValueError("n8n topVideos.id must be a non-empty string")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("n8n topVideos.title must be a non-empty string")
        published = item.get("published_at")
        if published is not None and not isinstance(published, str):
            raise ValueError("n8n topVideos.published_at must be a string or null")
        thumbnail = item.get("thumbnail_url")
        if thumbnail is not None:
            if not isinstance(thumbnail, str) or not thumbnail.startswith(("http://", "https://")):
                raise ValueError("n8n topVideos.thumbnail_url must be an http(s) URL or null")
        out.append({
            "id": video_id.strip(),
            "title": title.strip(),
            "views": count(item, "views"),
            "likes": count(item, "likes"),
            "comments": count(item, "comments"),
            "published_at": published,
            "thumbnail_url": thumbnail,
        })
    return out


def _parse_n8n_analysis(data: dict) -> dict:
    """Validate and normalize the schemaVersion 2 n8n response.

    v2 deliberately does not accept the former projection/profitability shape.
    Missing measurements remain null and are never replaced with arbitrary
    defaults.
    """
    if not isinstance(data, dict) or not data:
        raise ValueError("n8n returned an empty JSON response")
    if data.get("schemaVersion") != 2:
        raise ValueError("n8n returned an unsupported analysis schema")
    status = data.get("status")
    if status not in ("ready", "error"):
        raise ValueError("n8n response status must be ready or error")

    if status == "error":
        error = data.get("error")
        if not isinstance(error, dict):
            raise ValueError("n8n error response is missing error details")
        code = error.get("code")
        message = error.get("message")
        if not isinstance(code, str) or not code.strip():
            raise ValueError("n8n error.code must be a non-empty string")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("n8n error.message must be a non-empty string")
        return {
            "_status": "error",
            "analysis_version": 2,
            "error": f"{code.strip()}: {message.strip()[:500]}",
        }

    metrics = data.get("metrics")
    if not isinstance(metrics, dict):
        raise ValueError("n8n ready response is missing metrics")
    # A timestamp alone is not an observation.  Require at least one supplied
    # numeric measurement, while retaining legitimate zero values and nulls
    # for all other unavailable fields.
    if not any(metrics.get(key) is not None for key in _V2_METRIC_FIELDS):
        raise ValueError("n8n ready response contains no substantive metrics")
    normalized_metrics = {
        key: (_validated_metric(key, metrics.get(key)) if key in _V2_METRIC_FIELDS else metrics.get(key))
        for key in _V2_METRIC_FIELDS
    }
    for key in _V2_METRIC_DATES:
        value = metrics.get(key)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"n8n metrics.{key} must be a string or null")
        normalized_metrics[key] = value

    warnings = data.get("dataWarnings", [])
    if not isinstance(warnings, list) or any(not isinstance(w, str) for w in warnings):
        raise ValueError("n8n dataWarnings must be an array of strings")
    ai = data.get("aiInsights")
    if not isinstance(ai, dict):
        raise ValueError("n8n ready response is missing aiInsights")
    summary = ai.get("summary")
    if summary is not None and not isinstance(summary, str):
        raise ValueError("n8n aiInsights.summary must be a string or null")
    recommendations = ai.get("recommendations", [])
    if not isinstance(recommendations, list) or any(
        not isinstance(rec, str) for rec in recommendations
    ):
        raise ValueError("n8n aiInsights.recommendations must be an array of strings")

    return {
        "_status": "ready",
        "analysis_version": 2,
        "analysis_metrics": normalized_metrics,
        "data_warnings": warnings,
        "ai_summary": summary,
        "ai_recommendations": recommendations,
        "ai_sections": [],
        "top_videos": _parse_top_videos(data),
    }


def _clear_analysis_outputs(row) -> None:
    """Remove all result fields before/after a failed fresh attempt.

    The v1 columns are deliberately reset to compatibility-safe values but the
    historical MCN column is never touched.
    """
    row.analysis_metrics = None
    row.data_warnings = []
    row.analysis_version = None
    row.subs3 = None
    row.subs6 = None
    row.subs12 = None
    row.ai_summary = None
    row.ai_recommendations = []
    row.est_monthly_revenue = 0.0
    row.margin_percent = 0.0
    row.risk_level = "unknown"
    row.top_videos = []
    row.ai_sections = []
    row.avg_views = None
    row.avg_likes = None
    row.avg_comments = None
    row.engagement_rate = None


def _snapshot_timestamp(value: datetime) -> str:
    """Serialize DB's naive UTC timestamps for the n8n contract."""
    result = value.isoformat()
    return result if result.endswith("Z") else f"{result}Z"


def _history_payload(snapshots) -> list[dict] | None:
    """Normalize the bounded snapshot payload independently of database access."""
    if not snapshots:
        return None
    latest = sorted(snapshots, key=lambda snapshot: snapshot.fetched_at, reverse=True)
    return [
        {
            "recorded_at": _snapshot_timestamp(snapshot.fetched_at),
            "followers": snapshot.followers,
            "total_views": snapshot.total_views,
        }
        for snapshot in reversed(latest[:_MAX_ANALYSIS_HISTORY])
    ]


async def _analysis_history(channel_id: str) -> list[dict] | None:
    """Return a bounded, dated snapshot history or null when none exists."""
    async with AsyncSessionLocal() as db:
        snapshots = (
            await db.execute(
                select(SocialChannelSnapshot)
                .where(SocialChannelSnapshot.channel_id == channel_id)
                .order_by(SocialChannelSnapshot.fetched_at.desc())
                .limit(_MAX_ANALYSIS_HISTORY)
            )
        ).scalars().all()
    return _history_payload(snapshots)


async def _request_n8n_analysis(client, external_id: str, history: list[dict] | None) -> dict:
    """Fetch and validate one bounded n8n response.

    Parse JSON before interpreting HTTP status: n8n can return a useful
    schema-v2 error envelope with a 4xx/5xx status (notably YouTube quota
    failures).  A non-success status is only used as the fallback when no
    valid structured v2 error is present.
    """
    resp = await client.post(
        N8N_ANALYZE_URL,
        json={"channelId": external_id, "history": history},
        headers={"Content-Type": "application/json"},
    )
    status_code = int(getattr(resp, "status_code", 200))
    raw_content = getattr(resp, "content", None)
    if raw_content is not None:
        try:
            raw_size = len(raw_content.encode("utf-8") if isinstance(raw_content, str) else raw_content)
        except (TypeError, UnicodeError):
            raw_size = _MAX_N8N_RESPONSE_BYTES + 1
        if raw_size > _MAX_N8N_RESPONSE_BYTES:
            if status_code >= 400:
                raise _N8NHTTPStatusError(status_code)
            raise _N8NMalformedResponseError
        if not raw_content or not raw_content.strip():
            if status_code >= 400:
                raise _N8NHTTPStatusError(status_code)
            raise _N8NEmptyResponseError

    try:
        body = resp.json()
    except ValueError as exc:
        if status_code >= 400:
            raise _N8NHTTPStatusError(status_code) from exc
        raise _N8NMalformedResponseError from exc
    if body is None or body == {}:
        if status_code >= 400:
            raise _N8NHTTPStatusError(status_code)
        raise _N8NEmptyResponseError
    if not isinstance(body, dict):
        if status_code >= 400:
            raise _N8NHTTPStatusError(status_code)
        raise _N8NMalformedResponseError

    try:
        parsed = _parse_n8n_analysis(body)
    except ValueError as exc:
        if status_code >= 400:
            raise _N8NHTTPStatusError(status_code) from exc
        raise
    if status_code >= 400 and parsed.get("_status") != "error":
        raise _N8NHTTPStatusError(status_code)
    return parsed


async def _run_channel_analysis(channel_id: str, external_id: str) -> None:
    from ..models import SocialChannelAnalysis
    error: str | None = None
    parsed: dict | None = None

    try:
        import httpx
        history = await _analysis_history(channel_id)
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=15.0)) as client:
            # n8n is authoritative for all YouTube observations.  Do not
            # launch a second YouTube Data API workflow here.
            parsed = await _request_n8n_analysis(client, external_id, history)
    except Exception as e:
        # Persist only a user-safe message: httpx error strings embed the full
        # request URL (which can carry credentials in some deployments).
        import httpx
        if isinstance(e, _N8NHTTPStatusError):
            if e.status_code == 429:
                error = "n8n upstream rate limit (HTTP 429)"
            else:
                error = f"n8n returned HTTP {e.status_code}"
        elif isinstance(e, httpx.HTTPStatusError):
            # Defensive compatibility for custom HTTP clients; the regular
            # path uses _N8NHTTPStatusError after parsing the body.
            status_code = e.response.status_code
            if status_code == 429:
                error = "n8n upstream rate limit (HTTP 429)"
            else:
                error = f"n8n returned HTTP {status_code}"
        elif isinstance(e, httpx.TimeoutException):
            error = "n8n did not respond in time (timeout)"
        elif isinstance(e, httpx.HTTPError):
            error = "Could not reach the n8n analysis service"
        elif isinstance(e, _N8NEmptyResponseError):
            error = "n8n returned an empty JSON response"
        elif isinstance(e, _N8NMalformedResponseError):
            error = "n8n returned malformed JSON"
        elif isinstance(e, ValueError):
            error = "n8n returned an invalid schema v2 response"
        else:
            error = "Analysis failed — check api logs"
        # Never include the exception text: external clients can embed URLs or
        # request payloads in it.  The user-safe error above is sufficient.
        print(f"Socials channel analysis failed for {channel_id}: {type(e).__name__}")

    try:
        async with AsyncSessionLocal() as db:
            row = (await db.execute(select(SocialChannelAnalysis).where(
                SocialChannelAnalysis.channel_id == channel_id))).scalar_one_or_none()
            if row is None:
                return
            row.analyzed_at = datetime.utcnow()
            if error is not None or parsed is None or parsed.get("_status") == "error":
                _clear_analysis_outputs(row)
                row.status = "error"
                row.error = error or parsed.get("error")
                if parsed is not None and parsed.get("analysis_version") is not None:
                    row.analysis_version = parsed["analysis_version"]
            else:
                row.status = "ready"
                row.error = None
                _clear_analysis_outputs(row)
                for k, v in parsed.items():
                    if k.startswith("_"):
                        continue
                    setattr(row, k, v)
            await db.commit()
    except Exception as e:
        print(f"Socials channel analysis persistence failed for {channel_id}: {type(e).__name__}")


@router.post("/channels/{channel_id}/analyze", response_model=SocialChannelAnalysisOut)
async def analyze_social_channel(channel_id: str, db: AsyncSession = Depends(get_db)):
    from ..models import SocialChannelAnalysis
    c = await db.get(SocialChannel, channel_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    if c.platform != "youtube":
        raise HTTPException(status_code=400, detail="Analysis is only available for YouTube channels")
    if not c.external_id:
        raise HTTPException(status_code=400, detail="Channel has not synced yet — no YouTube channel ID resolved")

    # The lock serializes the whole check/upsert/spawn section so two
    # concurrent POSTs can never both spawn a run or race the unique
    # channel_id constraint (same pattern as /insights).
    async with _analysis_lock:
        row = (await db.execute(select(SocialChannelAnalysis).where(
            SocialChannelAnalysis.channel_id == channel_id))).scalar_one_or_none()

        task = _analysis_tasks.get(channel_id)
        if task is not None and not task.done() and row is not None:
            return _analysis_out(row)  # already running — treat POST as a poll

        if row is None:
            row = SocialChannelAnalysis(channel_id=channel_id)
            db.add(row)
        # A fresh attempt must not leave an earlier ready report visible while
        # this run is pending or if the new run fails.
        _clear_analysis_outputs(row)
        row.status = "running"
        row.error = None
        row.analyzed_at = datetime.utcnow()
        await db.commit()
        await db.refresh(row)
        _analysis_tasks[channel_id] = asyncio.create_task(
            _run_channel_analysis(channel_id, c.external_id))
        return _analysis_out(row)


@router.get("/channels/{channel_id}/analysis", response_model=SocialChannelAnalysisOut)
async def get_social_channel_analysis(channel_id: str, db: AsyncSession = Depends(get_db)):
    from ..models import SocialChannelAnalysis
    row = (await db.execute(select(SocialChannelAnalysis).where(
        SocialChannelAnalysis.channel_id == channel_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="No analysis for this channel yet")
    # A restart can strand a row in "running" — surface it as an error so the
    # UI doesn't poll forever.
    if row.status == "running":
        task = _analysis_tasks.get(channel_id)
        if (task is None or task.done()) and \
                (datetime.utcnow() - row.analyzed_at).total_seconds() > 600:
            _clear_analysis_outputs(row)
            row.status = "error"
            row.error = "Analysis was interrupted — run it again"
            await db.commit()
    return _analysis_out(row)


@router.post("/insights", response_model=SocialsInsightsOut)
async def generate_socials_insights(db: AsyncSession = Depends(get_db)):
    global _insights_task
    running = SocialsInsightsOut(
        status="running",
        generated_at=datetime.utcnow(),
        working=[],
        not_working=[],
        recommendations=[],
        model_used=False,
    )

    # The lock serializes the whole check/start section so two concurrent
    # POSTs can never both spawn a generation task.
    async with _insights_lock:
        if _insights_task is not None and not _insights_task.done():
            return running

        if _insights_task is not None and _insights_task.done():
            exc = _insights_task.exception()
            if exc is not None:
                _insights_task = None
                print(f"Socials insights: background task failed: {type(exc).__name__}")
                raise HTTPException(status_code=500, detail="Insight generation failed — check api logs")
            # Task finished successfully: deliver the cached result while fresh.
            if _insights_result is not None:
                age = (datetime.utcnow() - _insights_result.generated_at).total_seconds()
                if age < _INSIGHTS_CACHE_SECONDS:
                    return _insights_result
            _insights_task = None

        # Nothing running and no fresh cache — check there's data, then start.
        collected = await _collect_metrics_summary(db)
        if collected is None:
            raise HTTPException(status_code=404, detail="No social channels to analyze yet")
        _insights_task = asyncio.create_task(_insights_background())
    return running
