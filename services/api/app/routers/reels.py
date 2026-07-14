"""Prompt-based highlight reels across the library.

Segment selection happens here at request time (same embedding + Qdrant path
as semantic search, with an ilike fallback), so the worker only has to cut
and concatenate the chosen windows.
"""
import logging
import os
import re
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from ..database import get_db
from .projects import touch_project
from ..models import ReelJob, MediaAsset, TranscriptSegment, Scene
from ..schemas import ReelRequestIn, ReelJobOut, ReelClipOut
from ..worker_client import enqueue_reel

router = APIRouter(prefix="/reels", tags=["reels"])

logger = logging.getLogger("obtv.reels")

_VALID_PRESETS = ("original", "vertical")
# Widen short transcript hits so clips don't feel like jump cuts.
_MIN_CLIP_SECONDS = 6.0
_MAX_CLIP_SECONDS = 30.0
_LEAD_IN_SECONDS = 1.0


def _to_out(r: ReelJob) -> ReelJobOut:
    return ReelJobOut(
        id=r.id,
        prompt=r.prompt,
        media_id=r.media_id,
        project_id=r.project_id,
        preset=r.preset,
        burn_captions=r.burn_captions,
        clips=[ReelClipOut(**c) for c in (r.clips or [])],
        status=r.status,
        progress=r.progress or 0.0,
        output_url=f"/api/reels/{r.id}/download" if r.status == "success" and r.output_path else None,
        error_message=r.error_message,
        created_at=r.created_at,
        finished_at=r.finished_at,
    )


def _window(start: float, end: float, duration: float) -> tuple[float, float]:
    """Widen a transcript hit into a watchable clip window."""
    s = max(0.0, float(start) - _LEAD_IN_SECONDS)
    e = float(end)
    if e - s < _MIN_CLIP_SECONDS:
        e = s + _MIN_CLIP_SECONDS
    if e - s > _MAX_CLIP_SECONDS:
        e = s + _MAX_CLIP_SECONDS
    if duration > 0:
        e = min(e, duration)
    return s, e


def _merge_overlaps(clips: list[dict]) -> list[dict]:
    """Merge overlapping windows within the same asset, keep cross-asset order by score."""
    out: list[dict] = []
    for c in clips:
        merged = False
        for prev in out:
            if prev["media_id"] == c["media_id"] and not (
                c["start_time"] >= prev["end_time"] or c["end_time"] <= prev["start_time"]
            ):
                prev["start_time"] = min(prev["start_time"], c["start_time"])
                prev["end_time"] = max(prev["end_time"], c["end_time"])
                merged = True
                break
        if not merged:
            out.append(c)
    return out


async def _select_clips(
    prompt: str, max_clips: int, db: AsyncSession, media_id: str | None = None
) -> list[dict]:
    """Pick the best transcript moments for the prompt — across the whole
    library, or within one asset when media_id is set."""
    clips: list[dict] = []

    try:
        from ..services.embedding import get_text_embedding
        from ..services.qdrant_client import search_vectors

        vec = await get_text_embedding(prompt)
        vector_hits = await search_vectors(
            collection="transcripts", vector=vec, limit=max_clips * 3, media_id=media_id,
        )
        for hit in vector_hits:
            seg_id = hit.payload.get("segment_id")
            row = (await db.execute(
                select(TranscriptSegment, MediaAsset)
                .join(MediaAsset, TranscriptSegment.media_id == MediaAsset.id)
                .where(TranscriptSegment.id == seg_id)
            )).first()
            if not row:
                continue
            seg, asset = row
            s, e = _window(seg.start_time, seg.end_time, float(asset.duration_seconds or 0))
            clips.append({
                "media_id": asset.id,
                "filename": asset.filename,
                "start_time": s,
                "end_time": e,
                "snippet": seg.text,
                "_score": float(hit.score),
            })
    except Exception:
        logger.exception("Vector search failed for reel prompt %r — falling back to text search", prompt)

    if not clips:
        q = (
            select(TranscriptSegment, MediaAsset)
            .join(MediaAsset, TranscriptSegment.media_id == MediaAsset.id)
            .where(TranscriptSegment.text.ilike(f"%{prompt}%"))
        )
        if media_id:
            q = q.where(TranscriptSegment.media_id == media_id)
        rows = (await db.execute(q.limit(max_clips * 3))).all()
        for seg, asset in rows:
            s, e = _window(seg.start_time, seg.end_time, float(asset.duration_seconds or 0))
            clips.append({
                "media_id": asset.id,
                "filename": asset.filename,
                "start_time": s,
                "end_time": e,
                "snippet": seg.text,
                "_score": 0.5,
            })

    clips.sort(key=lambda c: c["_score"], reverse=True)
    clips = _merge_overlaps(clips)[:max_clips]
    for c in clips:
        c.pop("_score", None)
    # Story order: keep assets grouped and windows chronological within each.
    clips.sort(key=lambda c: (c["media_id"], c["start_time"]))

    await _attach_thumbnails(clips, db)
    return clips


async def _attach_thumbnails(clips: list[dict], db: AsyncSession) -> None:
    """Attach a preview frame to each clip: the scene covering (or nearest
    before) the clip start, falling back to the asset poster thumbnail."""
    for c in clips:
        thumb = None
        try:
            scene = (await db.execute(
                select(Scene)
                .where(Scene.media_id == c["media_id"], Scene.start_time <= c["start_time"])
                .order_by(Scene.start_time.desc())
                .limit(1)
            )).scalar_one_or_none()
            if scene is not None and scene.thumbnail_url:
                thumb = scene.thumbnail_url
            if not thumb:
                asset = (await db.execute(
                    select(MediaAsset).where(MediaAsset.id == c["media_id"])
                )).scalar_one_or_none()
                thumb = asset.thumbnail_url if asset is not None else None
        except Exception:
            logger.exception("Failed to attach thumbnail for reel clip %s", c["media_id"])
        c["thumbnail_url"] = thumb


async def _backfill_thumbnails(r: ReelJob, db: AsyncSession) -> None:
    """Reels created before clip previews existed have no thumbnail_url on
    their clips — attach and persist them once, on read."""
    clips = r.clips or []
    if not clips or all(c.get("thumbnail_url") for c in clips):
        return
    try:
        clips = [dict(c) for c in clips]
        await _attach_thumbnails(clips, db)
        r.clips = clips
        db.add(r)
        await db.commit()
    except Exception:
        logger.exception("Thumbnail backfill failed for reel %s", r.id)
        await db.rollback()


@router.get("", response_model=list[ReelJobOut])
async def list_reels(
    limit: int = 100, media_id: str | None = None, project_id: str | None = None,
    db: AsyncSession = Depends(get_db)
):
    q = select(ReelJob).order_by(desc(ReelJob.created_at))
    if media_id:
        q = q.where(ReelJob.media_id == media_id)
    if project_id:
        q = q.where(ReelJob.project_id == project_id)
    rows = (await db.execute(q.limit(min(max(limit, 1), 500)))).scalars().all()
    for r in rows:
        await _backfill_thumbnails(r, db)
    return [_to_out(r) for r in rows]


@router.post("", response_model=ReelJobOut, status_code=202)
async def create_reel(body: ReelRequestIn, db: AsyncSession = Depends(get_db)):
    prompt = body.prompt.strip()
    if len(prompt) < 3:
        raise HTTPException(status_code=400, detail="Prompt is too short")
    if body.preset not in _VALID_PRESETS:
        raise HTTPException(status_code=400, detail="Preset must be original or vertical")
    max_clips = min(max(body.max_clips, 1), 12)

    if body.media_id:
        asset = (await db.execute(
            select(MediaAsset).where(MediaAsset.id == body.media_id)
        )).scalar_one_or_none()
        if not asset:
            raise HTTPException(status_code=404, detail="Media asset not found")

    clips = await _select_clips(prompt, max_clips, db, media_id=body.media_id)
    if not clips:
        raise HTTPException(
            status_code=404,
            detail=(
                "No moments in this video match that prompt — try different wording"
                if body.media_id
                else "No moments in the library match that prompt — try different wording"
            ),
        )

    r = ReelJob(
        id=str(uuid.uuid4()),
        prompt=prompt,
        media_id=body.media_id,
        project_id=body.project_id,
        preset=body.preset,
        burn_captions=body.burn_captions,
        clips=clips,
        status="pending",
        progress=0.0,
        created_at=datetime.utcnow(),
    )
    db.add(r)
    await touch_project(db, r.project_id)
    await db.commit()

    try:
        await enqueue_reel(r.id)
    except Exception as exc:
        await db.rollback()
        r.status = "error"
        r.error_message = f"Failed to enqueue reel task: {exc}"
        r.finished_at = datetime.utcnow()
        db.add(r)
        await db.commit()
        raise HTTPException(status_code=503, detail="Queue unavailable — reel could not be started")
    return _to_out(r)


@router.get("/{id}", response_model=ReelJobOut)
async def get_reel(id: str, db: AsyncSession = Depends(get_db)):
    r = (await db.execute(select(ReelJob).where(ReelJob.id == id))).scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="Reel not found")
    await _backfill_thumbnails(r, db)
    return _to_out(r)


@router.delete("/{id}", status_code=204)
async def delete_reel(id: str, db: AsyncSession = Depends(get_db)):
    r = (await db.execute(select(ReelJob).where(ReelJob.id == id))).scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="Reel not found")
    if r.output_path and os.path.exists(r.output_path):
        try:
            os.remove(r.output_path)
        except OSError:
            pass
    await db.delete(r)
    await db.commit()


@router.get("/{id}/download")
async def download_reel(id: str, request: Request, db: AsyncSession = Depends(get_db)):
    r = (await db.execute(select(ReelJob).where(ReelJob.id == id))).scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="Reel not found")
    if r.status != "success" or not r.output_path or not os.path.exists(r.output_path):
        raise HTTPException(status_code=404, detail="Reel output not available")

    # Byte-range support so the browser <video> player can seek.
    range_header = request.headers.get("range")
    if range_header:
        file_size = os.path.getsize(r.output_path)
        m = re.match(r"bytes=(\d*)-(\d*)$", range_header.strip())
        if m:
            start_s, end_s = m.groups()
            start = int(start_s) if start_s else 0
            end = int(end_s) if end_s else file_size - 1
            end = min(end, file_size - 1)
            if start <= end:
                length = end - start + 1

                def _iter(path: str, offset: int, remaining: int, chunk: int = 1024 * 1024):
                    with open(path, "rb") as f:
                        f.seek(offset)
                        while remaining > 0:
                            data = f.read(min(chunk, remaining))
                            if not data:
                                break
                            remaining -= len(data)
                            yield data

                return StreamingResponse(
                    _iter(r.output_path, start, length),
                    status_code=206,
                    media_type="video/mp4",
                    headers={
                        "Content-Range": f"bytes {start}-{end}/{file_size}",
                        "Accept-Ranges": "bytes",
                        "Content-Length": str(length),
                    },
                )

    safe = "".join(ch if ch.isalnum() else "_" for ch in r.prompt[:40]).strip("_") or "reel"
    return FileResponse(
        r.output_path,
        media_type="video/mp4",
        filename=f"reel_{safe}_{r.id[:8]}.mp4",
        headers={"Accept-Ranges": "bytes"},
    )
