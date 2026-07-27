from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_admin
from ..database import get_db
from ..models import AuditLog
from ..schemas import AuditLogList, AuditLogOut

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=AuditLogList)
async def list_audit_log(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    q: str | None = None,
    username: str | None = None,
    method: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    require_admin(request)
    conds = []
    if q:
        conds.append(AuditLog.path.ilike(f"%{q}%"))
    if username:
        conds.append(AuditLog.username == username.strip().lower())
    if method:
        conds.append(AuditLog.method == method.strip().upper())

    total = (await db.execute(
        select(func.count()).select_from(AuditLog).where(*conds)
    )).scalar_one()
    rows = (await db.execute(
        select(AuditLog).where(*conds)
        .order_by(AuditLog.created_at.desc())
        .limit(limit).offset(offset)
    )).scalars().all()
    return AuditLogList(
        total=total,
        items=[AuditLogOut(
            id=r.id, created_at=r.created_at, user_id=r.user_id,
            username=r.username, method=r.method, path=r.path,
            status_code=r.status_code, ip=r.ip,
        ) for r in rows],
    )
