"""Persist independent scene results without holding locks across inference."""
import time

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


def _deadlock(exc):
    cause = getattr(exc, "orig", exc)
    return getattr(cause, "pgcode", None) == "40P01" or getattr(cause, "sqlstate", None) == "40P01"


def write_scene_result(db, scene_id: str, column: str, value: str, *, only_empty=False) -> bool:
    """One scene per transaction; retry only the DB write, never inference.

    Conditional descriptions make concurrent captioners and retries idempotent.
    A persistent deadlock is propagated to the task's error handler.
    """
    if column not in ("description", "embedding_id"):
        raise ValueError("Unsupported scene result column")
    statement = text(
        f"UPDATE scenes SET {column} = :value WHERE id = :sid"
        + (" AND (description IS NULL OR description = '')" if only_empty else "")
    )
    for attempt in range(4):
        try:
            result = db.execute(statement, {"value": value, "sid": scene_id})
            written = (result.rowcount or 0) > 0
            db.commit()
            return written
        except DBAPIError as exc:
            db.rollback()
            if not _deadlock(exc) or attempt == 3:
                raise
            time.sleep(0.05 * (2 ** attempt))