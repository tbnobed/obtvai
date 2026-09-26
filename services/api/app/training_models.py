"""Training records are separate from live inference and processing queues."""
from datetime import datetime
from sqlalchemy import String, Text, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base
from .models import gen_uuid


class TrainingExample(Base):
    __tablename__ = "training_examples"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String, default="draft")
    author: Mapped[str] = mapped_column(String, nullable=False)
    reviewer: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TrainingDataset(Base):
    __tablename__ = "training_datasets"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    manifest: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TrainingEvaluation(Base):
    __tablename__ = "training_evaluations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    dataset_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    report: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String, default="needs_review")
    reviewed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_scores: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)