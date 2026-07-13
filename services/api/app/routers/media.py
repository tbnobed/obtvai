import os
import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from ..database import get_db
from ..models import MediaAsset, Scene, TranscriptSegment, FaceCluster, ProcessingJob
from ..schemas import (
    MediaAssetOut, MediaListResponse, MediaIngestInput,
    LibraryStats, SceneOut, TranscriptSegmentOut, FaceClusterOut, FaceAppearance,
    ProcessingJobOut,
)
from ..config import settings
import redis.asyncio as aioredis

router = APIRouter(prefix="/media", tags=["media"])


def redis_client():
    return aioredis.from_url(settings.redis_url)


@router.get("/stats/summary", response_model=LibraryStats)
async def get_library_stats(db: AsyncSession = Depends(get_db)):
    total_q = await db.execute(select(func.count(MediaAsset.id)))
    total = total_q.scalar() or 0

    duration_q = await db.execute(select(func.sum(MediaAsset.duration_seconds)))
    total_duration = float(duration_q.scalar() or 0)

    storage_q = await db.execute(select(func.sum(MediaAsset.file_size_bytes)))
    storage_bytes = int(storage_q.scalar() or 0)

    status_q = await db.execute(
        select(MediaAsset.status, func.count(MediaAsset.id)).group_by(MediaAsset.status)
    )
    status_counts = {row[0]: row[1] for row in status_q.all()}

    recent_q = await db.execute(
        select(MediaAsset).order_by(desc(MediaAsset.created_at)).limit(5)
    )
    recent = recent_q.scalars().all()

    return LibraryStats(
        total_assets=total,
        total_duration_seconds=total_duration,
        status_counts=status_counts,
        storage_bytes=storage_bytes,
        recent_activity=[MediaAssetOut.model_validate(a) for a in recent],
    )


@router.get("", response_model=MediaListResponse)
async def list_media(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    q = select(MediaAsset).order_by(desc(MediaAsset.created_at))
    if status:
        q = q.where(MediaAsset.status == status)

    count_q = select(func.count()).select_from(q.subquery())
    total_r = await db.execute(count_q)
    total = total_r.scalar() or 0

    q = q.offset(offset).limit(limit)
    result = await db.execute(q)
    items = result.scalars().all()

    return MediaListResponse(
        items=[MediaAssetOut.model_validate(a) for a in items],
        total=total,
    )


@router.post("", response_model=MediaAssetOut, status_code=202)
async def ingest_media(body: MediaIngestInput, db: AsyncSession = Depends(get_db)):
    if not os.path.exists(body.file_path):
        raise HTTPException(status_code=400, detail=f"File not found: {body.file_path}")

    asset = MediaAsset(
        id=str(uuid.uuid4()),
        filename=body.title or os.path.basename(body.file_path),
        original_path=body.file_path,
        status="pending",
        file_size_bytes=os.path.getsize(body.file_path),
        created_at=datetime.utcnow(),
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)

    from ..worker_client import enqueue_ingest
    await enqueue_ingest(asset.id)

    return MediaAssetOut.model_validate(asset)


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".mxf", ".ts", ".m2ts", ".wmv", ".flv", ".webm"}


@router.post("/upload", response_model=MediaAssetOut, status_code=202)
async def upload_media(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    original_name = os.path.basename(file.filename or "")
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in VIDEO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext or 'unknown'}. Supported: {', '.join(sorted(VIDEO_EXTENSIONS))}",
        )

    os.makedirs(settings.upload_dir, exist_ok=True)
    asset_id = str(uuid.uuid4())
    dest_path = os.path.join(settings.upload_dir, f"{asset_id}_{original_name}")

    from fastapi.concurrency import run_in_threadpool

    total_bytes = 0
    try:
        with open(dest_path, "wb") as out:
            while True:
                chunk = await file.read(8 * 1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds the maximum upload size of {settings.max_upload_bytes} bytes",
                    )
                # Write off the event loop so multi-GB uploads don't starve the API.
                await run_in_threadpool(out.write, chunk)
    except HTTPException:
        try:
            if os.path.exists(dest_path):
                os.remove(dest_path)
        except OSError:
            pass
        raise
    except Exception:
        try:
            if os.path.exists(dest_path):
                os.remove(dest_path)
        except OSError:
            pass
        raise HTTPException(status_code=500, detail="Failed to save uploaded file")
    finally:
        await file.close()

    if os.path.getsize(dest_path) == 0:
        os.remove(dest_path)
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    asset = MediaAsset(
        id=asset_id,
        filename=title or original_name,
        original_path=dest_path,
        status="pending",
        file_size_bytes=os.path.getsize(dest_path),
        created_at=datetime.utcnow(),
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)

    from ..worker_client import enqueue_ingest
    await enqueue_ingest(asset.id)

    return MediaAssetOut.model_validate(asset)


@router.get("/{id}", response_model=MediaAssetOut)
async def get_media(id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MediaAsset).where(MediaAsset.id == id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Media not found")
    return MediaAssetOut.model_validate(asset)


@router.delete("/{id}", status_code=204)
async def delete_media(id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MediaAsset).where(MediaAsset.id == id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Media not found")
    original_path = asset.original_path
    await db.delete(asset)
    await db.commit()

    # Uploaded files live in our writable upload dir (unlike watched media,
    # which is mounted read-only and never touched) — clean them up.
    if original_path:
        upload_root = os.path.realpath(settings.upload_dir)
        real_path = os.path.realpath(original_path)
        if real_path.startswith(upload_root + os.sep) and os.path.isfile(real_path):
            try:
                os.remove(real_path)
            except OSError:
                import logging
                logging.getLogger("obtv.media").exception(
                    "Failed to delete uploaded file for media %s: %s", id, real_path
                )

    # Remove search vectors so deleted media stops surfacing in results.
    # Best-effort: DB row is already gone; log but don't fail if Qdrant is down.
    from ..services.qdrant_client import delete_by_media_id
    for collection in ("transcripts", "scenes"):
        try:
            await delete_by_media_id(collection, id)
        except Exception:
            import logging
            logging.getLogger("obtv.media").exception(
                "Failed to delete vectors for media %s from collection %s", id, collection
            )


@router.get("/{id}/scenes", response_model=list[SceneOut])
async def get_media_scenes(id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Scene).where(Scene.media_id == id).order_by(Scene.start_time)
    )
    return [SceneOut.model_validate(s) for s in result.scalars().all()]


@router.get("/{id}/transcript", response_model=list[TranscriptSegmentOut])
async def get_media_transcript(id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(TranscriptSegment)
        .where(TranscriptSegment.media_id == id)
        .order_by(TranscriptSegment.start_time)
    )
    return [TranscriptSegmentOut.model_validate(s) for s in result.scalars().all()]


@router.get("/{id}/faces", response_model=list[FaceClusterOut])
async def get_media_faces(id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(FaceCluster).where(FaceCluster.media_id == id)
    )
    clusters = result.scalars().all()
    out = []
    for c in clusters:
        appearances = [FaceAppearance(**a) for a in (c.appearances or [])]
        out.append(FaceClusterOut(
            cluster_id=c.cluster_id,
            media_id=c.media_id,
            label=c.label,
            thumbnail_url=c.thumbnail_url,
            appearances=appearances,
        ))
    return out


@router.get("/{id}/stream")
async def stream_media(id: str, db: AsyncSession = Depends(get_db)):
    from fastapi.responses import FileResponse
    result = await db.execute(select(MediaAsset).where(MediaAsset.id == id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Media not found")
    proxy = asset.proxy_path or asset.original_path
    if not proxy or not os.path.exists(proxy):
        raise HTTPException(status_code=404, detail="No streamable file available")
    return FileResponse(proxy, media_type="video/mp4")


@router.post("/{id}/highlight", response_model=ProcessingJobOut, status_code=202)
async def create_highlight(id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MediaAsset).where(MediaAsset.id == id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Media not found")
    if not asset.key_moments:
        raise HTTPException(
            status_code=400,
            detail="No key moments available — run AI analysis first",
        )

    existing = (
        await db.execute(
            select(ProcessingJob).where(
                ProcessingJob.media_id == id,
                ProcessingJob.job_type == "highlight",
                ProcessingJob.status.in_(("pending", "running")),
            )
        )
    ).scalars().first()
    if existing:
        out = ProcessingJobOut.model_validate(existing)
        out.filename = asset.filename
        return out

    job = ProcessingJob(media_id=id, job_type="highlight", status="pending", logs=[])
    db.add(job)
    await db.commit()
    await db.refresh(job)

    from ..worker_client import enqueue_job
    await enqueue_job("highlight", id, job.id)

    out = ProcessingJobOut.model_validate(job)
    out.filename = asset.filename
    return out


@router.get("/{id}/highlight/stream")
async def stream_highlight(id: str, db: AsyncSession = Depends(get_db)):
    from fastapi.responses import FileResponse
    result = await db.execute(select(MediaAsset).where(MediaAsset.id == id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Media not found")
    if not asset.highlight_url:
        raise HTTPException(status_code=404, detail="No highlight reel available")
    path = os.path.join(settings.artifacts_root, "reels", asset.highlight_url)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Highlight reel file missing")
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=f"highlight_{asset.filename.rsplit('.', 1)[0]}.mp4",
        content_disposition_type="inline",
    )
