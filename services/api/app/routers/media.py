import os
import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from ..database import get_db
from ..models import MediaAsset, Scene, TranscriptSegment, FaceCluster, ProcessingJob
from ..schemas import (
    MediaAssetOut, MediaListResponse, MediaIngestInput,
    LibraryStats, SceneOut, TranscriptSegmentOut, FaceClusterOut, FaceAppearance
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
    await db.delete(asset)
    await db.commit()


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
