"""Curator proxy-share browsing and selective ingest.

The Curator WebProxy share is mounted read-only at /curator. Admins browse
its folder structure here and flag folders for ingest; the watcher polls the
selected list and only ingests *_video.mp4 clips under selected folders.
"""
import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_admin
from ..config import settings
from ..database import get_db
from ..models import CuratorFolderSelection
from ..schemas import CuratorFolderListOut, CuratorFolderOut, CuratorFolderSelectInput

router = APIRouter(prefix="/curator", tags=["curator"])

CURATOR_ROOT = os.getenv("CURATOR_PROXY_ROOT", "/curator").rstrip("/")

# Walk guards so a huge SMB share can't hang the request: depth covers any
# sane content hierarchy, and the dir cap bounds total scandir calls.
MAX_DEPTH = int(os.getenv("CURATOR_SCAN_MAX_DEPTH", "6"))
MAX_DIRS = int(os.getenv("CURATOR_SCAN_MAX_DIRS", "5000"))


def _scan_tree() -> tuple[list[dict], bool]:
    """Walk the Curator share and return content folders (not per-clip proxy
    folders). A directory containing *_video.mp4 files is a clip folder — it
    counts toward its parent's clip_count and is not descended into."""
    items: list[dict] = []
    truncated = False
    visited = 0

    def walk(abs_dir: str, rel: str, depth: int) -> None:
        nonlocal visited, truncated
        if visited >= MAX_DIRS:
            truncated = True
            return
        visited += 1
        subdirs: list[tuple[str, str]] = []
        clip_count = 0
        try:
            with os.scandir(abs_dir) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            subdirs.append((entry.path, entry.name))
                        elif entry.name.lower().endswith("_video.mp4"):
                            clip_count += 1
                    except OSError:
                        continue
        except OSError:
            return
        if rel and clip_count == 0:
            # Flat layout puts _video.mp4 files directly in the content
            # folder; foldered layout nests one clip folder per proxy. Count
            # child clip folders without recording them as browsable folders.
            pass
        child_clip_dirs = 0
        deeper: list[tuple[str, str]] = []
        for sub_abs, sub_name in subdirs:
            has_video = False
            try:
                with os.scandir(sub_abs) as it:
                    for e in it:
                        if e.is_file(follow_symlinks=False) and e.name.lower().endswith("_video.mp4"):
                            has_video = True
                            break
            except OSError:
                continue
            if has_video:
                child_clip_dirs += 1
            else:
                deeper.append((sub_abs, sub_name))
        if rel:
            items.append({
                "path": rel,
                "name": os.path.basename(rel),
                "parent": os.path.dirname(rel) or None,
                "clip_count": clip_count + child_clip_dirs,
            })
        if depth >= MAX_DEPTH:
            return
        for sub_abs, sub_name in sorted(deeper, key=lambda t: t[1].lower()):
            walk(sub_abs, os.path.join(rel, sub_name) if rel else sub_name, depth + 1)

    walk(CURATOR_ROOT, "", 0)
    return items, truncated


def _safe_rel(path: str) -> str:
    rel = os.path.normpath(path.strip().strip("/"))
    if not rel or rel == "." or rel.startswith("..") or os.path.isabs(rel):
        raise HTTPException(status_code=400, detail="Invalid folder path")
    return rel


@router.get("/folders", response_model=CuratorFolderListOut)
async def list_curator_folders(request: Request, db: AsyncSession = Depends(get_db)):
    """Scan the Curator share's folder structure (admin only). Nothing is
    ingested by this call — it only reports what exists and what's selected."""
    require_admin(request)
    if not os.path.isdir(CURATOR_ROOT):
        raise HTTPException(status_code=503, detail="Curator share is not mounted")
    items, truncated = _scan_tree()
    selected = {
        r[0] for r in (await db.execute(select(CuratorFolderSelection.path))).all()
    }
    return CuratorFolderListOut(
        items=[
            CuratorFolderOut(**it, selected=(
                it["path"] in selected
                or any(it["path"] == s or it["path"].startswith(s + "/") for s in selected)
            ))
            for it in items
        ],
        truncated=truncated,
    )


@router.post("/folders/select", status_code=204)
async def select_curator_folder(
    body: CuratorFolderSelectInput, request: Request, db: AsyncSession = Depends(get_db)
):
    """Enable or disable ingest for a Curator folder (admin only). Enabling
    ingests existing clips within about a minute (watcher poll) and keeps
    watching for new ones; disabling stops future ingest but never removes
    already-ingested media."""
    require_admin(request)
    rel = _safe_rel(body.path)
    if body.selected:
        if not os.path.isdir(os.path.join(CURATOR_ROOT, rel)):
            raise HTTPException(status_code=404, detail="Folder not found on the Curator share")
        exists = (await db.execute(
            select(CuratorFolderSelection).where(CuratorFolderSelection.path == rel)
        )).scalar_one_or_none()
        if not exists:
            db.add(CuratorFolderSelection(path=rel))
    else:
        await db.execute(delete(CuratorFolderSelection).where(CuratorFolderSelection.path == rel))
    await db.commit()
    return None


@router.get("/selected")
async def list_selected(request: Request, db: AsyncSession = Depends(get_db)):
    """Machine-to-machine: the watcher polls this to know which Curator
    folders are ingest-enabled."""
    tok = request.headers.get("x-internal-token")
    if not (tok and settings.internal_api_token and secrets.compare_digest(tok, settings.internal_api_token)):
        raise HTTPException(status_code=403, detail="Internal endpoint")
    rows = (await db.execute(select(CuratorFolderSelection.path))).all()
    return {"paths": sorted(r[0] for r in rows)}
