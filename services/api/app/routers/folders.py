from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, delete

from ..database import get_db
from ..models import MediaFolder, MediaAsset
from ..schemas import MediaFolderOut, MediaFolderInput, MediaFolderUpdate

router = APIRouter(prefix="/folders", tags=["folders"])


async def _folder_out(db: AsyncSession, folder: MediaFolder) -> MediaFolderOut:
    count_q = await db.execute(
        select(func.count(MediaAsset.id)).where(MediaAsset.folder_id == folder.id)
    )
    return MediaFolderOut(
        id=folder.id,
        name=folder.name,
        parent_id=folder.parent_id,
        asset_count=count_q.scalar() or 0,
        created_at=folder.created_at,
    )


async def _is_descendant(db: AsyncSession, candidate: str, ancestor: str) -> bool:
    """True if `candidate` equals `ancestor` or lives anywhere under it."""
    result = await db.execute(select(MediaFolder.id, MediaFolder.parent_id))
    parents = {row[0]: row[1] for row in result.all()}
    cur: str | None = candidate
    seen: set[str] = set()
    while cur:
        if cur == ancestor:
            return True
        if cur in seen:
            return False
        seen.add(cur)
        cur = parents.get(cur)
    return False


@router.get("", response_model=list[MediaFolderOut])
async def list_folders(db: AsyncSession = Depends(get_db)):
    counts_q = await db.execute(
        select(MediaAsset.folder_id, func.count(MediaAsset.id))
        .where(MediaAsset.folder_id.is_not(None))
        .group_by(MediaAsset.folder_id)
    )
    counts = {row[0]: row[1] for row in counts_q.all()}
    result = await db.execute(select(MediaFolder).order_by(func.lower(MediaFolder.name)))
    return [
        MediaFolderOut(
            id=f.id,
            name=f.name,
            parent_id=f.parent_id,
            asset_count=counts.get(f.id, 0),
            created_at=f.created_at,
        )
        for f in result.scalars().all()
    ]


@router.post("", response_model=MediaFolderOut, status_code=201)
async def create_folder(payload: MediaFolderInput, db: AsyncSession = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Folder name is required")
    if payload.parent_id:
        parent_q = await db.execute(select(MediaFolder.id).where(MediaFolder.id == payload.parent_id))
        if parent_q.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Parent folder not found")
    folder = MediaFolder(name=name, parent_id=payload.parent_id)
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return await _folder_out(db, folder)


@router.patch("/{folder_id}", response_model=MediaFolderOut)
async def update_folder(folder_id: str, payload: MediaFolderUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MediaFolder).where(MediaFolder.id == folder_id))
    folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Folder name is required")
        folder.name = name
    if "parent_id" in data:
        parent_id = data["parent_id"]
        if parent_id:
            parent_q = await db.execute(select(MediaFolder.id).where(MediaFolder.id == parent_id))
            if parent_q.scalar_one_or_none() is None:
                raise HTTPException(status_code=404, detail="Parent folder not found")
            if parent_id == folder.id or await _is_descendant(db, parent_id, folder.id):
                raise HTTPException(
                    status_code=400,
                    detail="Cannot move a folder into itself or its own subfolder",
                )
        folder.parent_id = parent_id
    await db.commit()
    await db.refresh(folder)
    return await _folder_out(db, folder)


@router.delete("/{folder_id}", status_code=204)
async def delete_folder(folder_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MediaFolder).where(MediaFolder.id == folder_id))
    folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    # Contents move up to the deleted folder's parent — never delete media.
    await db.execute(
        update(MediaAsset)
        .where(MediaAsset.folder_id == folder_id)
        .values(folder_id=folder.parent_id)
    )
    await db.execute(
        update(MediaFolder)
        .where(MediaFolder.parent_id == folder_id)
        .values(parent_id=folder.parent_id)
    )
    await db.execute(delete(MediaFolder).where(MediaFolder.id == folder_id))
    await db.commit()
    return None
