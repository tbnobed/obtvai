import uuid
import csv
import json
import io
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from ..database import get_db
from ..models import ClipList, Clip, MediaAsset
from ..schemas import (
    ClipListOut, ClipOut, ClipListInput, ClipListUpdate,
    ClipExportInput, ClipExportResult,
    RenderPresetInput, RenderJobOut,
)

router = APIRouter(prefix="/clips", tags=["clips"])


async def _load_clip_list(id: str, db: AsyncSession) -> ClipList:
    result = await db.execute(
        select(ClipList).where(ClipList.id == id)
    )
    cl = result.scalar_one_or_none()
    if not cl:
        raise HTTPException(status_code=404, detail="Clip list not found")
    return cl


async def _build_clip_out(clip: Clip, db: AsyncSession) -> ClipOut:
    asset = (await db.execute(select(MediaAsset).where(MediaAsset.id == clip.media_id))).scalar_one_or_none()
    return ClipOut(
        id=clip.id,
        media_id=clip.media_id,
        filename=asset.filename if asset else None,
        start_time=clip.start_time,
        end_time=clip.end_time,
        label=clip.label,
        notes=clip.notes,
    )


async def _build_clip_list_out(cl: ClipList, db: AsyncSession) -> ClipListOut:
    clips_q = await db.execute(
        select(Clip).where(Clip.clip_list_id == cl.id).order_by(Clip.position)
    )
    clips = clips_q.scalars().all()
    clip_outs = [await _build_clip_out(c, db) for c in clips]
    return ClipListOut(
        id=cl.id,
        name=cl.name,
        description=cl.description,
        created_at=cl.created_at,
        clips=clip_outs,
    )


@router.get("", response_model=list[ClipListOut])
async def list_clip_lists(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ClipList).order_by(desc(ClipList.created_at))
    )
    cls = result.scalars().all()
    return [await _build_clip_list_out(cl, db) for cl in cls]


@router.post("", response_model=ClipListOut, status_code=201)
async def create_clip_list(body: ClipListInput, db: AsyncSession = Depends(get_db)):
    cl = ClipList(
        id=str(uuid.uuid4()),
        name=body.name,
        description=body.description,
        created_at=datetime.utcnow(),
    )
    db.add(cl)
    await db.flush()

    for i, c in enumerate(body.clips or []):
        clip = Clip(
            id=str(uuid.uuid4()),
            clip_list_id=cl.id,
            media_id=c.media_id,
            start_time=c.start_time,
            end_time=c.end_time,
            label=c.label,
            position=i,
        )
        db.add(clip)

    await db.commit()
    await db.refresh(cl)
    return await _build_clip_list_out(cl, db)


@router.get("/{id}", response_model=ClipListOut)
async def get_clip_list(id: str, db: AsyncSession = Depends(get_db)):
    cl = await _load_clip_list(id, db)
    return await _build_clip_list_out(cl, db)


@router.patch("/{id}", response_model=ClipListOut)
async def update_clip_list(id: str, body: ClipListUpdate, db: AsyncSession = Depends(get_db)):
    cl = await _load_clip_list(id, db)
    if body.name is not None:
        cl.name = body.name
    if body.description is not None:
        cl.description = body.description
    if body.clips is not None:
        existing_q = await db.execute(select(Clip).where(Clip.clip_list_id == cl.id))
        for c in existing_q.scalars().all():
            await db.delete(c)
        for i, c in enumerate(body.clips):
            clip = Clip(
                id=str(uuid.uuid4()),
                clip_list_id=cl.id,
                media_id=c.media_id,
                start_time=c.start_time,
                end_time=c.end_time,
                label=c.label,
                position=i,
            )
            db.add(clip)
    await db.commit()
    await db.refresh(cl)
    return await _build_clip_list_out(cl, db)


@router.delete("/{id}", status_code=204)
async def delete_clip_list(id: str, db: AsyncSession = Depends(get_db)):
    cl = await _load_clip_list(id, db)
    await db.delete(cl)
    await db.commit()


@router.post("/{id}/export", response_model=ClipExportResult)
async def export_clip_list(id: str, body: ClipExportInput, db: AsyncSession = Depends(get_db)):
    cl = await _load_clip_list(id, db)
    cl_out = await _build_clip_list_out(cl, db)

    fmt = body.format.lower()
    if fmt not in ("edl", "csv", "json"):
        raise HTTPException(status_code=400, detail="Format must be edl, csv, or json")

    if fmt == "json":
        content = json.dumps(
            {"name": cl_out.name, "clips": [c.model_dump() for c in cl_out.clips]},
            indent=2, default=str,
        )
        filename = f"{cl_out.name.replace(' ', '_')}.json"

    elif fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["clip_id", "filename", "start_time", "end_time", "label"])
        for c in cl_out.clips:
            writer.writerow([c.id, c.filename, c.start_time, c.end_time, c.label or ""])
        content = buf.getvalue()
        filename = f"{cl_out.name.replace(' ', '_')}.csv"

    else:
        lines = ["TITLE: " + cl_out.name, "FCM: NON-DROP FRAME", ""]
        for i, c in enumerate(cl_out.clips, 1):
            def tc(secs: float) -> str:
                h = int(secs // 3600)
                m = int((secs % 3600) // 60)
                s = int(secs % 60)
                f = int((secs % 1) * 25)
                return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"
            lines.append(f"{i:03d}  AX       V     C        {tc(c.start_time)} {tc(c.end_time)} {tc(c.start_time)} {tc(c.end_time)}")
            lines.append(f"* FROM CLIP NAME: {c.filename}")
            if c.label:
                lines.append(f"* COMMENT: {c.label}")
            lines.append("")
        content = "\n".join(lines)
        filename = f"{cl_out.name.replace(' ', '_')}.edl"

    return ClipExportResult(format=fmt, content=content, filename=filename)


@router.post("/{id}/render", response_model=list[RenderJobOut], status_code=202)
async def render_clip_list(id: str, body: RenderPresetInput, db: AsyncSession = Depends(get_db)):
    from .renders import create_renders_for_clip_list
    return await create_renders_for_clip_list(id, body.preset, body.burn_captions, db)
