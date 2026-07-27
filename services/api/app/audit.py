"""Audit trail: record every mutating API request (and login attempts) with
the acting user. Writes run as fire-and-forget background tasks on their own
session — they never block or fail the request."""
import asyncio
import logging
import random
from datetime import datetime, timedelta

from sqlalchemy import delete

from .database import AsyncSessionLocal
from .models import AuditLog

logger = logging.getLogger(__name__)

AUDITED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

RETENTION = timedelta(days=365)

# Keep strong references so pending writes aren't garbage-collected.
_pending: set[asyncio.Task] = set()


def record_audit_bg(**kwargs) -> None:
    """Schedule an audit write without blocking the request."""
    task = asyncio.get_running_loop().create_task(record_audit(**kwargs))
    _pending.add(task)
    task.add_done_callback(_pending.discard)


async def record_audit(
    *,
    user=None,
    username: str | None = None,
    method: str,
    path: str,
    status_code: int,
    ip: str | None = None,
) -> None:
    try:
        async with AsyncSessionLocal() as db:
            db.add(AuditLog(
                created_at=datetime.utcnow(),
                user_id=getattr(user, "id", None),
                username=username or (user.username if user is not None else None),
                method=method,
                path=path[:500],
                status_code=status_code,
                ip=ip,
            ))
            # Opportunistic retention prune (~1 in 500 writes).
            if random.random() < 0.002:
                await db.execute(delete(AuditLog).where(
                    AuditLog.created_at < datetime.utcnow() - RETENTION))
            await db.commit()
    except Exception:  # noqa: BLE001 — auditing must never break the request
        logger.exception("audit write failed for %s %s", method, path)
