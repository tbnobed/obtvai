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
