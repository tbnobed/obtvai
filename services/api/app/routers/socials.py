"""Social media performance: programs, channels, snapshots, posts.

Channel/post metrics are fetched by the worker (tasks/social_sync.py) on a
beat schedule or via POST /socials/refresh. This router manages the
program/channel registry and reads stored metrics; week-over-week deltas are
computed at read time from snapshots.
"""
import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func

from ..database import get_db
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

    prog_name = {p.id: p.name for p in programs}
    week_ago_ts = datetime.utcnow() - timedelta(days=7)
    lines: list[str] = []
    stats: dict = {"channels": []}

    for c in channels:
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
                .limit(12)
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
        if top is not None:
            parts.append(f'best post "{(top.title or top.external_id)[:70]}" {top.views} views')
        if bottom is not None and bottom is not top:
            parts.append(f'weakest post "{(bottom.title or bottom.external_id)[:70]}" {bottom.views} views')
        if c.last_error:
            parts.append(f"SYNC ERROR: {c.last_error[:120]}")
        lines.append(" ".join(parts))
        stats["channels"].append({
            "name": name, "growth": growth, "avg_views": avg_views,
            "engagement": eng, "top": top, "bottom": bottom, "error": c.last_error,
        })

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
        line = raw.strip().lstrip("-• ").strip()
        upper = line.upper()
        if upper.startswith("WORKING:"):
            working.append(line[len("WORKING:"):].strip())
        elif upper.startswith("NOT WORKING:"):
            not_working.append(line[len("NOT WORKING:"):].strip())
        elif upper.startswith("RECOMMEND:"):
            recs.append(line[len("RECOMMEND:"):].strip())
    return working[:6], not_working[:6], recs[:5]


@router.post("/insights", response_model=SocialsInsightsOut)
async def generate_socials_insights(db: AsyncSession = Depends(get_db)):
    collected = await _collect_metrics_summary(db)
    if collected is None:
        raise HTTPException(status_code=404, detail="No social channels to analyze yet")
    summary, stats = collected

    prompt = (
        "You are a social media analyst for a TV broadcaster. Below are current "
        "metrics for the station's social channels, grouped by program "
        "(one line per channel):\n\n"
        f"{summary}\n\n"
        "Analyze what is working and what is not. Compare platforms and programs, "
        "call out breakout posts and weak content formats by name, and flag any "
        "sync errors as problems. Base every point strictly on the numbers above — "
        "do not invent data.\n\n"
        "Answer ONLY with lines in exactly this format (3-6 of each):\n"
        "WORKING: <one specific observation>\n"
        "NOT WORKING: <one specific observation>\n"
        "RECOMMEND: <one specific, actionable suggestion>"
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
    except Exception:
        pass
    if not model_used:
        working, not_working, recs = _heuristic_insights(stats)

    return SocialsInsightsOut(
        generated_at=datetime.utcnow(),
        working=working,
        not_working=not_working,
        recommendations=recs,
        model_used=model_used,
    )
