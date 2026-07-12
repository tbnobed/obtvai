"""Shared helpers for all worker tasks."""
import os
import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from ..db import get_session


def _get_job_and_asset(db: Session, job_id: str):
    from sqlalchemy import text
    row = db.execute(
        text("""
            SELECT j.id, j.media_id, j.job_type, j.status, j.logs, j.retry_count,
                   a.filename, a.original_path, a.proxy_path
            FROM processing_jobs j
            JOIN media_assets a ON a.id = j.media_id
            WHERE j.id = :jid
        """),
        {"jid": job_id},
    ).fetchone()
    return row


def update_job(db: Session, job_id: str, **kwargs):
    from sqlalchemy import text
    set_parts = ", ".join(f"{k} = :{k}" for k in kwargs)
    db.execute(text(f"UPDATE processing_jobs SET {set_parts} WHERE id = :jid"), {**kwargs, "jid": job_id})
    db.commit()


def append_log(db: Session, job_id: str, message: str):
    from sqlalchemy import text
    db.execute(
        text("""
            UPDATE processing_jobs
            SET logs = logs || :msg::jsonb
            WHERE id = :jid
        """),
        {"msg": f'["{message}"]', "jid": job_id},
    )
    db.commit()


def create_job(db: Session, media_id: str, job_type: str) -> str:
    from sqlalchemy import text
    job_id = str(uuid.uuid4())
    db.execute(
        text("""
            INSERT INTO processing_jobs (id, media_id, job_type, status, logs, retry_count, created_at)
            VALUES (:id, :media_id, :job_type, 'pending', '[]', 0, :now)
        """),
        {"id": job_id, "media_id": media_id, "job_type": job_type, "now": datetime.utcnow()},
    )
    db.commit()
    return job_id


def update_asset(db: Session, media_id: str, **kwargs):
    from sqlalchemy import text
    set_parts = ", ".join(f"{k} = :{k}" for k in kwargs)
    db.execute(text(f"UPDATE media_assets SET {set_parts} WHERE id = :mid"), {**kwargs, "mid": media_id})
    db.commit()
