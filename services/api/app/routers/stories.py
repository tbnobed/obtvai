"""Multi-video story builder jobs."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from ..database import get_db
from .projects import touch_project
from ..models import StoryJob, MediaAsset
from ..schemas import StoryRequestIn, StoryJobOut
from ..worker_client import enqueue_story

router = APIRouter(prefix="/stories", tags=["stories"])


def _to_out(s: StoryJob) -> StoryJobOut:
    return StoryJobOut(
        id=s.id,
        prompt=s.prompt,
        project_id=s.project_id,
        asset_ids=list(s.asset_ids or []),
        status=s.status,
        progress=s.progress or 0.0,
        title=s.title,
        narrative=s.narrative,
        clip_list_id=s.clip_list_id,
        error_message=s.error_message,
        created_at=s.created_at,
        finished_at=s.finished_at,
    )


@router.get("", response_model=list[StoryJobOut])
async def list_stories(limit: int = 100, project_id: str | None = None, db: AsyncSession = Depends(get_db)):
    q = select(StoryJob).order_by(desc(StoryJob.created_at))
    if project_id:
        q = q.where(StoryJob.project_id == project_id)
    rows = (await db.execute(q.limit(min(max(limit, 1), 500)))).scalars().all()
    return [_to_out(s) for s in rows]


@router.post("", response_model=StoryJobOut, status_code=202)
async def create_story(body: StoryRequestIn, db: AsyncSession = Depends(get_db)):
    asset_ids = [a for a in dict.fromkeys(body.asset_ids) if a]
    if not asset_ids:
        raise HTTPException(status_code=400, detail="Pick at least one asset")

    found = (await db.execute(
        select(MediaAsset.id).where(MediaAsset.id.in_(asset_ids))
    )).scalars().all()
    missing = set(asset_ids) - set(found)
    if missing:
        raise HTTPException(status_code=404, detail=f"Unknown assets: {', '.join(sorted(missing))}")

    story = StoryJob(
        prompt=(body.prompt or "").strip() or None,
        project_id=body.project_id,
        asset_ids=asset_ids,
        status="pending",
    )
    db.add(story)
    await touch_project(db, story.project_id)
    await db.commit()
    await db.refresh(story)

    await enqueue_story(story.id)
    return _to_out(story)


@router.get("/{id}", response_model=StoryJobOut)
async def get_story(id: str, db: AsyncSession = Depends(get_db)):
    s = (await db.execute(select(StoryJob).where(StoryJob.id == id))).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Story not found")
    return _to_out(s)


@router.delete("/{id}", status_code=204)
async def delete_story(id: str, db: AsyncSession = Depends(get_db)):
    s = (await db.execute(select(StoryJob).where(StoryJob.id == id))).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Story not found")
    await db.delete(s)
    await db.commit()
