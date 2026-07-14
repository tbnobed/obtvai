"""Projects — unified editorial workflow containers."""
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, update
from ..database import get_db
from ..models import Project, ClipList, RenderJob, ReelJob, StoryJob
from ..schemas import ProjectOut, ProjectInput, ProjectUpdate, ProjectCounts

router = APIRouter(prefix="/projects", tags=["projects"])


async def touch_project(db: AsyncSession, project_id: str | None) -> None:
    """Bump a project's updated_at when linked work is created/changed. Caller commits."""
    if not project_id:
        return
    await db.execute(
        update(Project).where(Project.id == project_id).values(updated_at=datetime.utcnow())
    )


async def _counts(db: AsyncSession, project_id: str) -> ProjectCounts:
    async def count(model) -> int:
        return (await db.execute(
            select(func.count()).select_from(model).where(model.project_id == project_id)
        )).scalar_one()

    return ProjectCounts(
        clip_lists=await count(ClipList),
        stories=await count(StoryJob),
        reels=await count(ReelJob),
        renders=await count(RenderJob),
    )


async def _to_out(p: Project, db: AsyncSession) -> ProjectOut:
    return ProjectOut(
        id=p.id,
        name=p.name,
        description=p.description,
        script=p.script,
        status=p.status or "active",
        created_at=p.created_at,
        updated_at=p.updated_at,
        counts=await _counts(db, p.id),
    )


async def _load(id: str, db: AsyncSession) -> Project:
    p = (await db.execute(select(Project).where(Project.id == id))).scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    return p


@router.get("", response_model=list[ProjectOut])
async def list_projects(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(Project).order_by(desc(Project.created_at))
    )).scalars().all()
    return [await _to_out(p, db) for p in rows]


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(body: ProjectInput, db: AsyncSession = Depends(get_db)):
    p = Project(
        id=str(uuid.uuid4()),
        name=body.name.strip(),
        description=body.description,
        script=body.script,
        created_at=datetime.utcnow(),
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return await _to_out(p, db)


@router.get("/{id}", response_model=ProjectOut)
async def get_project(id: str, db: AsyncSession = Depends(get_db)):
    p = await _load(id, db)
    return await _to_out(p, db)


@router.patch("/{id}", response_model=ProjectOut)
async def update_project(id: str, body: ProjectUpdate, db: AsyncSession = Depends(get_db)):
    p = await _load(id, db)
    if body.name is not None:
        p.name = body.name.strip()
    if "description" in body.model_fields_set:
        p.description = body.description
    if "script" in body.model_fields_set:
        p.script = body.script
    if body.status is not None:
        p.status = body.status
    p.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(p)
    return await _to_out(p, db)


@router.delete("/{id}", status_code=204)
async def delete_project(id: str, db: AsyncSession = Depends(get_db)):
    p = await _load(id, db)
    # Keep linked items; just unlink them from the deleted project.
    for model in (ClipList, RenderJob, ReelJob, StoryJob):
        await db.execute(
            update(model).where(model.project_id == id).values(project_id=None)
        )
    await db.delete(p)
    await db.commit()
