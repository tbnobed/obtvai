"""New tables only; no ALTERs on busy media/worker tables."""
from datetime import datetime
from sqlalchemy import String, Text, DateTime, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


class CatalogCheckpoint(Base):
    __tablename__ = "curator_catalog_checkpoints"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    cursor: Mapped[dict] = mapped_column(JSONB, nullable=False)
    stats: Mapped[dict] = mapped_column(JSONB, default=dict)
    last_error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CatalogAsset(Base):
    __tablename__ = "curator_catalog_assets"
    asset_id: Mapped[str] = mapped_column(String, primary_key=True)
    asset_type: Mapped[str] = mapped_column(String, nullable=False)
    metadata_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String, index=True)
    error: Mapped[str | None] = mapped_column(Text)
    media_id: Mapped[str | None] = mapped_column(String)
    job_id: Mapped[str | None] = mapped_column(String)
    task_id: Mapped[str | None] = mapped_column(String)
    dispatch_state: Mapped[str | None] = mapped_column(String)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CatalogRun(Base):
    __tablename__ = "curator_catalog_runs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    options: Mapped[dict] = mapped_column(JSONB, nullable=False)
    stats: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)