"""Admin-only catalog controls. Discovery is never enabled by API startup."""
from fastapi import APIRouter, Depends, Request, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from ..auth import require_admin
from ..database import get_db
from ..catalog_models import CatalogAsset, CatalogCheckpoint, CatalogRun
from ..catalog_service import CatalogOptions, run_catalog
from ..commands.import_curator_workbook import ImportFailure
from ..catalog import cutoff
from datetime import datetime

router = APIRouter(prefix="/curator/catalog", tags=["curator"])


@router.get("")
async def status(request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    checkpoint = await db.get(CatalogCheckpoint, "catalog")
    runner = await db.get(CatalogCheckpoint, "runner")
    fresh = runner is not None and (datetime.utcnow() - runner.updated_at).total_seconds() < max(
        300, 3 * runner.cursor.get("interval_seconds", 60))
    counts = (await db.execute(select(CatalogAsset.status, func.count())
                              .group_by(CatalogAsset.status))).all()
    runs = (await db.execute(select(CatalogRun).order_by(CatalogRun.started_at.desc()).limit(20))).scalars().all()
    return {"automatic_discovery": bool(fresh and not runner.cursor.get("paused") and
                                       runner.cursor.get("state") in ("running", "waiting")),
            "cutoff": cutoff().isoformat(), "runner": runner, "runner_heartbeat_fresh": fresh,
            "counts": dict(counts), "checkpoint": checkpoint, "runs": runs}


@router.post("/runner/resume")
async def resume(request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    row = await db.get(CatalogCheckpoint, "runner")
    if not row:
        raise HTTPException(404, "No managed catalog runner has registered")
    row.cursor = {**row.cursor, "paused": False, "consecutive_errors": 0, "state": "resumed"}
    row.last_error = None
    await db.commit()
    return {"note": "Pause cleared. A running managed runner may admit the next bounded asset; a stopped service is not started."}


@router.get("/assets")
async def assets(request: Request, status: str = "review",
                 after: str = "", limit: int = Query(default=100, ge=1, le=199),
                 db: AsyncSession = Depends(get_db)):
    require_admin(request)
    rows = (await db.execute(select(CatalogAsset).where(
        CatalogAsset.status == status, CatalogAsset.asset_id > after
    ).order_by(CatalogAsset.asset_id).limit(limit))).scalars().all()
    return {"items": rows, "next": rows[-1].asset_id if rows else None}


@router.post("/assets/{asset_id}/retry")
async def retry_asset(asset_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    row = await db.get(CatalogAsset, asset_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Catalog asset not found")
    if row.status != "failed":
        raise HTTPException(status_code=409, detail="Only terminal failed catalog assets may be reset")
    row.attempts, row.status, row.error = 0, "retry", None
    await db.commit()
    return {"asset_id": asset_id, "status": "retry", "note": "Reset only; next explicitly authorized bounded run may queue it"}


@router.post("/run")
async def run(request: Request, body: CatalogOptions):
    require_admin(request)
    try:
        return await run_catalog(body)
    except ImportFailure as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc