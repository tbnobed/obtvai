"""Admission budget for the benchmark library; caller holds the catalog lock."""
import os

from sqlalchemy import func, select, or_

from .catalog_models import CatalogCheckpoint
from .models import MediaAsset, ProcessingJob


async def library_limit(db, candidate=None):
    limit = int(os.getenv("CURATOR_CATALOG_READY_LIMIT", "0"))
    if limit <= 0:
        return None
    ready = (await db.execute(select(func.count()).select_from(MediaAsset).where(
        MediaAsset.status == "ready"
    ))).scalar()
    cap = await db.get(CatalogCheckpoint, "library_limit")
    if cap is None:
        cap = CatalogCheckpoint(id="library_limit", cursor={}, stats={})
        db.add(cap)
    latched = cap.cursor.get("reached") and cap.cursor.get("limit") == limit
    reserved_ids = set((await db.execute(select(MediaAsset.id).where(
        MediaAsset.status != "ready",
        or_(MediaAsset.status.in_(("pending", "processing")),
            MediaAsset.id.in_(select(ProcessingJob.media_id).where(
                ProcessingJob.status.in_(("pending", "running"))))),
    ))).scalars())
    cap.cursor = {"limit": limit, "ready": ready, "reserved": len(reserved_ids),
                  "reached": bool(latched or ready >= limit)}
    from datetime import datetime
    cap.updated_at = datetime.utcnow()
    if cap.cursor["reached"]:
        from .catalog_recovery import pause
        await pause(db, f"Benchmark library limit reached: {ready} ready assets; target {limit}. "
                        "New catalog ingestion is stopped. Running jobs may finish.")
        await db.commit()
        return "library_limit_reached"
    await db.commit()
    if candidate is not None:
        existing_ready = candidate.media_id and (await db.execute(select(MediaAsset.id).where(
            MediaAsset.id == candidate.media_id, MediaAsset.status == "ready"
        ))).scalar()
        cost = 0 if existing_ready or candidate.media_id in reserved_ids else 1
        if ready + len(reserved_ids) + cost > limit:
            return "library_limit_draining"
    return None
