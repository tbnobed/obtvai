"""Prompt-based highlight reels across the library.

Segment selection happens here at request time (same embedding + Qdrant path
as semantic search, with an ilike fallback), so the worker only has to cut
and concatenate the chosen windows.
"""
import logging
import os
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from ..database import get_db
from ..models import ReelJob, MediaAsset, TranscriptSegment
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


async def _select_clips(prompt: str, max_clips: int, db: AsyncSession) -> list[dict]:
    """Pick the best transcript moments for the prompt across the whole library."""
    hits: list[tuple[str, float, float, str | None, float]] = []  # (seg_id, ...) via rows below
    clips: list[dict] = []

    try:
        from ..services.embedding import get_text_embedding
        from ..services.qdrant_client import search_vectors

        vec = await get_text_embedding(prompt)
        vector_hits = await search_vectors(
            collection="transcripts", vector=vec, limit=max_clips * 3, media_id=None,
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
        rows = (await db.execute(
            select(TranscriptSegment, MediaAsset)
            .join(MediaAsset, TranscriptSegment.media_id == MediaAsset.id)
            .where(TranscriptSegment.text.ilike(f"%{prompt}%"))
            .limit(max_clips * 3)
        )).all()
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
    return clips


@router.get("", response_model=list[ReelJobOut])
async def list_reels(limit: int = 100, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(ReelJob).order_by(desc(ReelJob.created_at)).limit(min(max(limit, 1), 500))
    )).scalars().all()
    return [_to_out(r) for r in rows]


@router.post("", response_model=ReelJobOut, status_code=202)
async def create_reel(body: ReelRequestIn, db: AsyncSession = Depends(get_db)):
    prompt = body.prompt.strip()
    if len(prompt) < 3:
        raise HTTPException(status_code=400, detail="Prompt is too short")
    if body.preset not in _VALID_PRESETS:
        raise HTTPException(status_code=400, detail="Preset must be original or vertical")
    max_clips = min(max(body.max_clips, 1), 12)

    clips = await _select_clips(prompt, max_clips, db)
    if not clips:
        raise HTTPException(
            status_code=404,
            detail="No moments in the library match that prompt — try different wording",
        )

    r = ReelJob(
        id=str(uuid.uuid4()),
        prompt=prompt,
        preset=body.preset,
        burn_captions=body.burn_captions,
        clips=clips,
        status="pending",
        progress=0.0,
        created_at=datetime.utcnow(),
    )
    db.add(r)
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
async def download_reel(id: str, db: AsyncSession = Depends(get_db)):
    r = (await db.execute(select(ReelJob).where(ReelJob.id == id))).scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="Reel not found")
    if r.status != "success" or not r.output_path or not os.path.exists(r.output_path):
        raise HTTPException(status_code=404, detail="Reel output not available")
    safe = "".join(ch if ch.isalnum() else "_" for ch in r.prompt[:40]).strip("_") or "reel"
    return FileResponse(r.output_path, media_type="video/mp4", filename=f"reel_{safe}_{r.id[:8]}.mp4")
