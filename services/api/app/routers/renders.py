import os
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from ..database import get_db
from ..models import RenderJob, MediaAsset, ClipList, Clip
from ..schemas import (
    RenderJobOut, RenderRequestIn, RenderPresetInput,
    PublishRequestIn, PublishPlatformsOut,
)
from ..worker_client import enqueue_render, enqueue_publish
from ..config import settings

router = APIRouter(prefix="/renders", tags=["renders"])

_VALID_PRESETS = ("original", "vertical")


def _youtube_configured() -> bool:
    return bool(
        settings.youtube_client_id
        and settings.youtube_client_secret
        and settings.youtube_refresh_token
    )


def _to_out(r: RenderJob, filename: str | None) -> RenderJobOut:
    return RenderJobOut(
        id=r.id,
        media_id=r.media_id,
        filename=filename,
        clip_list_id=r.clip_list_id,
        project_id=r.project_id,
        label=r.label,
        start_time=r.start_time,
        end_time=r.end_time,
        preset=r.preset,
        burn_captions=r.burn_captions,
        status=r.status,
        progress=r.progress or 0.0,
        output_url=f"/api/renders/{r.id}/download" if r.status == "success" and r.output_path else None,
        error_message=r.error_message,
        publish_status=r.publish_status,
        publish_url=r.publish_url,
        publish_error=r.publish_error,
        created_at=r.created_at,
        finished_at=r.finished_at,
    )


async def _asset_filename(db: AsyncSession, media_id: str) -> str | None:
    asset = (await db.execute(
        select(MediaAsset.filename).where(MediaAsset.id == media_id)
    )).scalar_one_or_none()
    return asset


async def _mark_enqueue_failed(db: AsyncSession, r: RenderJob, exc: Exception, publish: bool = False):
    """If the queue is unreachable after commit, don't leave the job stuck in pending."""
    await db.rollback()
    if publish:
        r.publish_status = "error"
        r.publish_error = f"Failed to enqueue publish task: {exc}"
    else:
        r.status = "error"
        r.error_message = f"Failed to enqueue render task: {exc}"
        r.finished_at = datetime.utcnow()
    db.add(r)
    await db.commit()


def _validate(preset: str, start_time: float, end_time: float):
    if preset not in _VALID_PRESETS:
        raise HTTPException(status_code=400, detail="Preset must be original or vertical")
    if end_time <= start_time:
        raise HTTPException(status_code=400, detail="end_time must be after start_time")


async def _create_render(
    db: AsyncSession,
    media_id: str,
    start_time: float,
    end_time: float,
    preset: str,
    burn_captions: bool,
    label: str | None = None,
    clip_list_id: str | None = None,
    project_id: str | None = None,
) -> RenderJob:
    r = RenderJob(
        id=str(uuid.uuid4()),
        media_id=media_id,
        clip_list_id=clip_list_id,
        project_id=project_id,
        label=label,
        start_time=start_time,
        end_time=end_time,
        preset=preset,
        burn_captions=burn_captions,
        status="pending",
        progress=0.0,
        created_at=datetime.utcnow(),
    )
    db.add(r)
    return r


@router.get("", response_model=list[RenderJobOut])
async def list_renders(
    clip_list_id: str | None = None,
    project_id: str | None = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(RenderJob, MediaAsset.filename)
        .join(MediaAsset, RenderJob.media_id == MediaAsset.id)
        .order_by(desc(RenderJob.created_at))
        .limit(min(max(limit, 1), 500))
    )
    if clip_list_id:
        q = q.where(RenderJob.clip_list_id == clip_list_id)
    if project_id:
        q = q.where(RenderJob.project_id == project_id)
    rows = (await db.execute(q)).all()
    return [_to_out(r, fn) for r, fn in rows]


@router.post("", response_model=RenderJobOut, status_code=202)
async def create_render(body: RenderRequestIn, db: AsyncSession = Depends(get_db)):
    _validate(body.preset, body.start_time, body.end_time)
    filename = await _asset_filename(db, body.media_id)
    if filename is None:
        raise HTTPException(status_code=404, detail="Media not found")
    r = await _create_render(
        db, body.media_id, body.start_time, body.end_time,
        body.preset, body.burn_captions, body.label, body.clip_list_id, body.project_id,
    )
    await db.commit()
    try:
        await enqueue_render(r.id)
    except Exception as exc:
        await _mark_enqueue_failed(db, r, exc)
        raise HTTPException(status_code=503, detail="Queue unavailable — render could not be started")
    return _to_out(r, filename)


@router.get("/publish/platforms", response_model=PublishPlatformsOut)
async def get_publish_platforms():
    return PublishPlatformsOut(youtube=_youtube_configured())


@router.get("/{id}", response_model=RenderJobOut)
async def get_render(id: str, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(
        select(RenderJob, MediaAsset.filename)
        .join(MediaAsset, RenderJob.media_id == MediaAsset.id)
        .where(RenderJob.id == id)
    )).first()
    if not row:
        raise HTTPException(status_code=404, detail="Render not found")
    r, fn = row
    return _to_out(r, fn)


@router.delete("/{id}", status_code=204)
async def delete_render(id: str, db: AsyncSession = Depends(get_db)):
    r = (await db.execute(select(RenderJob).where(RenderJob.id == id))).scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="Render not found")
    if r.output_path and os.path.exists(r.output_path):
        try:
            os.remove(r.output_path)
        except OSError:
            pass
    await db.delete(r)
    await db.commit()


@router.get("/{id}/download")
async def download_render(id: str, db: AsyncSession = Depends(get_db)):
    r = (await db.execute(select(RenderJob).where(RenderJob.id == id))).scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="Render not found")
    if r.status != "success" or not r.output_path or not os.path.exists(r.output_path):
        raise HTTPException(status_code=404, detail="Render output not available")
    suffix = "vertical" if r.preset == "vertical" else "clip"
    name = f"{(r.label or suffix).replace(' ', '_')}_{r.id[:8]}.mp4"
    return FileResponse(r.output_path, media_type="video/mp4", filename=name)


@router.post("/{id}/publish", response_model=RenderJobOut, status_code=202)
async def publish_render(id: str, body: PublishRequestIn, db: AsyncSession = Depends(get_db)):
    if body.platform != "youtube":
        raise HTTPException(status_code=400, detail="Only youtube publishing is supported")
    if not _youtube_configured():
        raise HTTPException(
            status_code=400,
            detail="YouTube is not configured — set YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN",
        )
    if body.privacy not in ("public", "unlisted", "private"):
        raise HTTPException(status_code=400, detail="privacy must be public, unlisted or private")

    row = (await db.execute(
        select(RenderJob, MediaAsset.filename)
        .join(MediaAsset, RenderJob.media_id == MediaAsset.id)
        .where(RenderJob.id == id)
        .with_for_update(of=RenderJob)
    )).first()
    if not row:
        raise HTTPException(status_code=404, detail="Render not found")
    r, fn = row
    if r.status != "success" or not r.output_path:
        raise HTTPException(status_code=400, detail="Render is not finished yet")
    if r.publish_status in ("pending", "running"):
        raise HTTPException(status_code=400, detail="Publish already in progress")

    r.publish_status = "pending"
    r.publish_error = None
    r.publish_url = None
    await db.commit()
    try:
        await enqueue_publish_with_meta(r.id, body)
    except Exception as exc:
        await _mark_enqueue_failed(db, r, exc, publish=True)
        raise HTTPException(status_code=503, detail="Queue unavailable — publish could not be started")
    return _to_out(r, fn)


async def enqueue_publish_with_meta(render_id: str, body: PublishRequestIn):
    from ..worker_client import _publish
    import uuid as _uuid
    await _publish(
        "cpu",
        "tasks.publish.publish_render",
        {
            "render_id": render_id,
            "title": body.title,
            "description": body.description or "",
            "tags": body.tags,
            "privacy": body.privacy,
        },
        str(_uuid.uuid4()),
    )


async def create_renders_for_clip_list(
    clip_list_id: str, preset: str, burn_captions: bool, db: AsyncSession
) -> list[RenderJobOut]:
    _validate(preset, 0.0, 1.0)
    cl = (await db.execute(select(ClipList).where(ClipList.id == clip_list_id))).scalar_one_or_none()
    if not cl:
        raise HTTPException(status_code=404, detail="Clip list not found")
    clips = (await db.execute(
        select(Clip).where(Clip.clip_list_id == clip_list_id).order_by(Clip.position)
    )).scalars().all()
    if not clips:
        raise HTTPException(status_code=400, detail="Clip list has no clips")

    created: list[RenderJob] = []
    for c in clips:
        if c.end_time <= c.start_time:
            continue
        r = await _create_render(
            db, c.media_id, c.start_time, c.end_time,
            preset, burn_captions, c.label, clip_list_id, cl.project_id,
        )
        created.append(r)
    if not created:
        raise HTTPException(status_code=400, detail="No valid clips to render")
    await db.commit()

    outs: list[RenderJobOut] = []
    for r in created:
        try:
            await enqueue_render(r.id)
        except Exception as exc:
            await _mark_enqueue_failed(db, r, exc)
        outs.append(_to_out(r, await _asset_filename(db, r.media_id)))
    return outs
