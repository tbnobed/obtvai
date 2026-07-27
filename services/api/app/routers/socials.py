"""Social media performance: programs, channels, snapshots, posts.

Channel/post metrics are fetched by the worker (tasks/social_sync.py) on a
beat schedule or via POST /socials/refresh. This router manages the
program/channel registry and reads stored metrics; week-over-week deltas are
computed at read time from snapshots.
"""
import asyncio
import os
from datetime import datetime, timedelta

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
                f"RECOMMEND lines parsed; first 300 chars: {answer[:300]!r}"
            )
    except Exception as e:
        print(f"Socials insights: LLM generation failed: {type(e).__name__}: {e}")
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
        print(f"Socials insights: failed to persist result: {type(e).__name__}: {e}")
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
        print(f"Socials insights: history prune failed (non-fatal): {type(e).__name__}: {e}")


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
# Server-side only — never expose this key to the frontend.
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
_YT_API = "https://www.googleapis.com/youtube/v3"
_analysis_tasks: dict[str, asyncio.Task] = {}
_analysis_lock = asyncio.Lock()  # serializes analyze-start across channels


def _analysis_out(a) -> SocialChannelAnalysisOut:
    return SocialChannelAnalysisOut(
        channel_id=a.channel_id,
        status=a.status,
        error=a.error,
        analyzed_at=a.analyzed_at,
        subs3=a.subs3,
        subs6=a.subs6,
        subs12=a.subs12,
        ai_summary=a.ai_summary,
        ai_recommendations=a.ai_recommendations or [],
        est_monthly_revenue=a.est_monthly_revenue or 0,
        margin_percent=a.margin_percent or 0,
        mcn_share_percent=a.mcn_share_percent or 0,
        risk_level=a.risk_level or "unknown",
        top_videos=a.top_videos or [],
        ai_sections=a.ai_sections or [],
        avg_views=a.avg_views,
        avg_likes=a.avg_likes,
        avg_comments=a.avg_comments,
        engagement_rate=a.engagement_rate,
    )


import re as _re

_HEADING_BODY_SPLIT = _re.compile(
    r"\s(?=(?:The|This|That|These|A|An|In|It|If|With|While|Based|Focus|Given|Regularly|Overall|Despite|Although|To|By|For)\b)")


def _clean_md(s: str) -> str:
    """Strip markdown emphasis/heading tokens so text renders as plain prose."""
    s = _re.sub(r"\*\*(.*?)\*\*", r"\1", s)
    s = _re.sub(r"__(.*?)__", r"\1", s)
    s = _re.sub(r"`([^`]*)`", r"\1", s)
    s = _re.sub(r"^#{1,6}\s*", "", s)
    s = _re.sub(r"\s+", " ", s)
    return s.strip(" \t-–—:*•")


def _parse_ai_sections(text: str) -> list[dict]:
    """Break an LLM markdown narrative (### headings, **bold**, numbered/dash
    lists — sometimes flattened onto a single line) into structured sections:
    [{title, body, bullets[]}]."""
    if not text or ("#" not in text and "**" not in text and "\n- " not in text):
        return []

    # If newlines were lost, re-introduce them before headings and list markers.
    if len(text.splitlines()) <= 2:
        text = _re.sub(r"\s*(#{2,6}\s)", r"\n\1", text)
        text = _re.sub(r"\s+(-\s+\*\*)", r"\n\1", text)
        text = _re.sub(r"\s+(\d{1,2}\.\s+\*\*)", r"\n\1", text)

    sections: list[dict] = []
    cur: dict = {"title": None, "body": [], "bullets": []}

    def push():
        nonlocal cur
        if cur["title"] or cur["body"] or cur["bullets"]:
            sections.append({
                "title": cur["title"],
                "body": " ".join(cur["body"]) or None,
                "bullets": cur["bullets"][:12],
            })
        cur = {"title": None, "body": [], "bullets": []}

    for ln in text.splitlines():
        t = ln.strip()
        if not t:
            continue
        m = _re.match(r"#{2,6}\s*(.+)", t)
        if m:
            push()
            heading = _clean_md(m.group(1))
            # Flattened input can glue the first body sentence onto the heading.
            if len(heading) > 30:
                parts = _HEADING_BODY_SPLIT.split(heading, maxsplit=1)
                if len(parts) == 2 and len(parts[0]) <= 60:
                    heading, rest = parts[0], parts[1]
                    cur["body"].append(rest.strip())
                elif len(heading) > 100:
                    # No clean sentence boundary — keep a readable prefix.
                    words = heading.split()
                    heading, rest = " ".join(words[:8]), " ".join(words[8:])
                    if rest:
                        cur["body"].append(rest)
            cur["title"] = heading.rstrip(".")
            continue
        m = _re.match(r"(?:[-*•]|\d{1,2}[.)])\s+(.+)", t)
        if m:
            b = _clean_md(m.group(1))
            if b:
                cur["bullets"].append(b)
            continue
        p = _clean_md(t)
        if p:
            cur["body"].append(p)
    push()
    return sections[:12]


def _parse_top_videos(data: dict) -> list[dict]:
    """Pull the top-videos list out of the n8n response, tolerating different
    key names and item shapes (dicts with varying field names, or plain strings)."""
    raw = None
    for key in ("topVideos", "top_videos", "topPerformingContent", "topContent",
                "topPosts", "bestPerforming", "topPerforming"):
        v = data.get(key)
        if isinstance(v, list) and v:
            raw = v
            break
    if raw is None:
        return []

    def _int(v):
        try:
            return int(float(v)) if v is not None else None
        except (TypeError, ValueError):
            return None

    def pick(item: dict, *keys):
        for k in keys:
            v = item.get(k)
            if v not in (None, ""):
                return v
        return None

    out: list[dict] = []
    for item in raw[:10]:
        if isinstance(item, str):
            if item.strip():
                out.append({"title": item.strip()})
            continue
        if not isinstance(item, dict):
            continue
        title = pick(item, "title", "name", "videoTitle", "video_title")
        if not title:
            continue
        def _url(v):
            # Only allow http(s) URLs — anything else (javascript:, data:, ...)
            # is dropped so it can never reach an <a href> in the UI.
            s = str(v).strip() if v is not None else ""
            return s if s.startswith(("http://", "https://")) else None

        out.append({
            "title": str(title).strip(),
            "url": _url(pick(item, "url", "link", "videoUrl", "video_url")),
            "thumbnail": _url(pick(item, "thumbnail", "thumbnailUrl", "thumbnail_url", "image")),
            "views": _int(pick(item, "views", "viewCount", "view_count")),
            "likes": _int(pick(item, "likes", "likeCount", "like_count")),
            "comments": _int(pick(item, "comments", "commentCount", "comment_count")),
            "published_at": (lambda v: str(v).strip() if v is not None else None)(
                pick(item, "publishedAt", "published_at", "published", "date")),
        })
    return out


def _parse_n8n_analysis(data: dict) -> dict:
    """Map the n8n response onto our columns, tolerating missing fields."""
    def _int(v):
        try:
            return int(float(v)) if v is not None else None
        except (TypeError, ValueError):
            return None

    def _float(v, default=0.0):
        try:
            return float(v) if v is not None else default
        except (TypeError, ValueError):
            return default

    proj = data.get("projections") or {}
    prof = data.get("profitability") or {}
    risk = data.get("riskAnalysis") or {}

    ai = data.get("aiInsights")
    summary: str | None = None
    recs: list[str] = []
    sections: list[dict] = []
    if isinstance(ai, str):
        sections = _parse_ai_sections(ai)
        if sections:
            # Prefer the "Overview"/"Summary" section body; fall back to the
            # first section with a substantive body.
            summary = next(
                (s["body"] for s in sections
                 if s.get("body") and s.get("title")
                 and _re.search(r"overview|summary", s["title"], _re.I)),
                None,
            ) or next((s["body"] for s in sections
                       if s.get("body") and len(s["body"]) > 40), None)
        else:
            summary = _clean_md(ai) or None
    elif isinstance(ai, dict):
        s = ai.get("summary")
        if s:
            sections = _parse_ai_sections(str(s))
            summary = (next((x["body"] for x in sections if x.get("body")), None)
                       if sections else _clean_md(str(s)) or None)
        raw_recs = ai.get("recommendations")
        if isinstance(raw_recs, list):
            recs = [_clean_md(str(r)) for r in raw_recs if _clean_md(str(r))]

    level = risk.get("level")
    return {
        "subs3": _int(proj.get("subs3")),
        "subs6": _int(proj.get("subs6")),
        "subs12": _int(proj.get("subs12")),
        "ai_summary": summary,
        "ai_recommendations": recs,
        "ai_sections": sections,
        "est_monthly_revenue": _float(prof.get("estMonthlyRevenue")),
        "margin_percent": _float(prof.get("marginPercent")),
        "mcn_share_percent": _int(prof.get("mcnSharePercent")) or 0,
        "risk_level": (str(level).strip().lower() if level else "unknown") or "unknown",
        "top_videos": _parse_top_videos(data),
    }


async def _yt_search_ids(client, external_id: str, order: str, max_results: int) -> list[str]:
    """search.list returns only video IDs; stats come from a videos.list batch."""
    resp = await client.get(f"{_YT_API}/search", params={
        "key": YOUTUBE_API_KEY, "channelId": external_id, "part": "id",
        "type": "video", "order": order, "maxResults": max_results,
    })
    resp.raise_for_status()
    return [
        it["id"]["videoId"]
        for it in resp.json().get("items", [])
        if isinstance(it.get("id"), dict) and it["id"].get("videoId")
    ]


async def _yt_videos(client, ids: list[str]) -> list[dict]:
    if not ids:
        return []
    resp = await client.get(f"{_YT_API}/videos", params={
        "key": YOUTUBE_API_KEY, "part": "snippet,statistics", "id": ",".join(ids),
    })
    resp.raise_for_status()
    return resp.json().get("items", [])


def _yt_stat(v: dict, key: str) -> int:
    try:
        return int(v.get("statistics", {}).get(key) or 0)
    except (TypeError, ValueError):
        return 0


async def _fetch_youtube_stats(external_id: str) -> dict:
    """Two parallel YouTube Data API v3 flows:
    - order=date, 10 latest videos  -> avg views/likes/comments + engagement rate
    - order=viewCount, top of 50    -> top-5 videos list with snippet+stats
    """
    import httpx
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        recent_ids, top_ids = await asyncio.gather(
            _yt_search_ids(client, external_id, "date", 10),
            _yt_search_ids(client, external_id, "viewCount", 50),
        )
        recent, top = await asyncio.gather(
            _yt_videos(client, recent_ids),
            _yt_videos(client, top_ids[:5]),
        )

    out: dict = {}
    if recent:
        n = len(recent)
        tv = sum(_yt_stat(v, "viewCount") for v in recent)
        tl = sum(_yt_stat(v, "likeCount") for v in recent)
        tc = sum(_yt_stat(v, "commentCount") for v in recent)
        out.update(
            avg_views=tv / n,
            avg_likes=tl / n,
            avg_comments=tc / n,
            engagement_rate=((tl + tc) / tv * 100) if tv else 0.0,
        )

    # videos.list does not preserve request order — re-sort by views.
    top_sorted = sorted(top, key=lambda v: _yt_stat(v, "viewCount"), reverse=True)
    out["top_videos"] = [
        {
            "title": (v.get("snippet", {}).get("title") or "Untitled").strip(),
            "url": f"https://www.youtube.com/watch?v={v.get('id')}",
            "thumbnail": (v.get("snippet", {}).get("thumbnails", {}).get("medium", {}) or {}).get("url"),
            "views": _yt_stat(v, "viewCount"),
            "likes": _yt_stat(v, "likeCount"),
            "comments": _yt_stat(v, "commentCount"),
            "published_at": v.get("snippet", {}).get("publishedAt"),
        }
        for v in top_sorted
        if v.get("id")
    ]
    return out


def _yt_safe_error(e: Exception) -> str:
    """httpx error strings embed the full request URL including the API key —
    never log or persist them raw."""
    import httpx
    if isinstance(e, httpx.HTTPStatusError):
        return f"YouTube API returned HTTP {e.response.status_code}"
    if isinstance(e, httpx.TimeoutException):
        return "YouTube API timed out"
    if isinstance(e, httpx.HTTPError):
        return "Could not reach the YouTube API"
    return f"YouTube fetch failed ({type(e).__name__})"


async def _run_channel_analysis(channel_id: str, external_id: str) -> None:
    from ..models import SocialChannelAnalysis
    error: str | None = None
    parsed: dict | None = None

    # Kick off the YouTube stats fetch in parallel with the n8n call.
    yt_task: asyncio.Task | None = None
    if YOUTUBE_API_KEY:
        yt_task = asyncio.create_task(_fetch_youtube_stats(external_id))
    else:
        print("Socials channel analysis: YOUTUBE_API_KEY not set — skipping YouTube stats")

    try:
        import httpx
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=15.0)) as client:
            resp = await client.post(
                N8N_ANALYZE_URL,
                json={"channelId": external_id},
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            body = resp.json()
        if isinstance(body, list):  # n8n webhooks often wrap output in a list
            body = body[0] if body else {}
        if not isinstance(body, dict):
            raise ValueError("n8n returned an unexpected response shape")
        parsed = _parse_n8n_analysis(body)
    except Exception as e:
        # Persist only a user-safe message: httpx error strings embed the full
        # request URL (which can carry credentials in some deployments).
        import httpx
        if isinstance(e, httpx.HTTPStatusError):
            error = f"n8n returned HTTP {e.response.status_code}"
        elif isinstance(e, httpx.TimeoutException):
            error = "n8n did not respond in time (timeout)"
        elif isinstance(e, httpx.HTTPError):
            error = "Could not reach the n8n analysis service"
        elif isinstance(e, ValueError):
            error = "n8n returned an unexpected response"
        else:
            error = "Analysis failed — check api logs"
        print(f"Socials channel analysis failed for {channel_id}: {type(e).__name__}: {str(e)[:300]}")

    yt_data: dict | None = None
    if yt_task is not None:
        try:
            yt_data = await yt_task
        except Exception as e:
            print(f"Socials channel analysis: {_yt_safe_error(e)} for {channel_id}")

    # Ready if either source produced data; error only when both failed.
    if yt_data:
        merged = dict(parsed or {})
        merged.update({k: v for k, v in yt_data.items() if k != "top_videos"})
        # YouTube's top-5 by viewCount wins over anything n8n reported.
        if yt_data.get("top_videos"):
            merged["top_videos"] = yt_data["top_videos"]
        elif parsed:
            merged["top_videos"] = parsed.get("top_videos") or []
        parsed = merged
        error = None
    elif parsed is None:
        error = error or "Analysis failed — check api logs"

    try:
        async with AsyncSessionLocal() as db:
            row = (await db.execute(select(SocialChannelAnalysis).where(
                SocialChannelAnalysis.channel_id == channel_id))).scalar_one_or_none()
            if row is None:
                return
            row.analyzed_at = datetime.utcnow()
            if error is not None:
                row.status = "error"
                row.error = error
            else:
                row.status = "ready"
                row.error = None
                for k, v in (parsed or {}).items():
                    setattr(row, k, v)
            await db.commit()
    except Exception as e:
        print(f"Socials channel analysis: failed to persist for {channel_id}: {type(e).__name__}: {e}")


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
                print(f"Socials insights: background task failed: {type(exc).__name__}: {exc}")
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
