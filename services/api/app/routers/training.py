"""Admin-only curated datasets. Training runs externally, never on ingest GPUs."""
import json
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..auth import require_admin
from ..database import get_db
from ..training_models import TrainingExample, TrainingDataset, TrainingEvaluation
from ..training_service import prepare_dataset, validate_report

router = APIRouter(prefix="/training", tags=["training"])


class ExampleInput(BaseModel):
    instruction: str = Field(min_length=3, max_length=4000)
    context: str = Field(max_length=16000)
    answer: str = Field(min_length=3, max_length=16000)
    source_ref: str = Field(min_length=3, max_length=500)
    group: str = Field(min_length=3, max_length=200)
    rights_approved: bool = False
    required_terms: list[str] = Field(default_factory=list, max_length=20)
    expected_format: Literal["text", "json"] = "text"

    @field_validator("instruction", "answer", "source_ref", "group")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("Cannot be blank")
        return value.strip()

    @field_validator("required_terms")
    @classmethod
    def terms(cls, values):
        if any(not t.strip() or len(t) > 100 for t in values):
            raise ValueError("Required terms must be nonblank and at most 100 characters.")
        return [t.strip() for t in values]


class ReviewInput(BaseModel):
    status: Literal["approved", "rejected", "draft"]


class DatasetInput(BaseModel):
    base_model: str = Field(min_length=3, max_length=250)
    base_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    license_note: str = Field(min_length=10, max_length=2000)


class EvaluationInput(BaseModel):
    report: dict


class ApprovalInput(BaseModel):
    decision: Literal["approved_for_manual_trial", "rejected"]
    note: str = Field(min_length=20, max_length=4000)
    checked_grounding_and_style: bool
    scores: dict[str, int]

    @field_validator("scores")
    @classmethod
    def rubric(cls, value):
        if set(value) != {"baseline_grounding", "candidate_grounding", "baseline_style", "candidate_style"} or any(
                score < 1 or score > 5 for score in value.values()):
            raise ValueError("Four human grounding/style scores from 1 to 5 are required.")
        return value


async def get_row(db, model, key):
    row = await db.get(model, key)
    if row is None:
        raise HTTPException(404, "Record not found")
    return row


@router.get("")
async def state(request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    examples = (await db.execute(select(TrainingExample).order_by(TrainingExample.updated_at.desc()))).scalars().all()
    datasets = (await db.execute(select(TrainingDataset).order_by(TrainingDataset.created_at.desc()))).scalars().all()
    reports = (await db.execute(select(TrainingEvaluation).order_by(TrainingEvaluation.created_at.desc()))).scalars().all()
    return {"execution_mode": "external_dedicated_host", "examples": [
        {"id": e.id, **e.data, "status": e.status, "author": e.author, "reviewer": e.reviewer} for e in examples],
        "datasets": [{"id": d.id, "base_model": d.manifest["base_model"], "base_revision": d.manifest["base_revision"],
                      "dataset_hash": d.manifest["dataset_hash"], "train_count": len(d.manifest["train"]),
                      "heldout_count": len(d.manifest["heldout"]), "created_at": d.created_at} for d in datasets],
        "evaluations": [{"id": r.id, "dataset_id": r.dataset_id, "status": r.status,
                         "review_note": r.review_note, "review_scores": r.review_scores, "report": r.report} for r in reports]}


@router.post("/examples", status_code=201)
async def create(body: ExampleInput, request: Request, db: AsyncSession = Depends(get_db)):
    user = require_admin(request)
    row = TrainingExample(data=body.model_dump(), author=user.username, status="draft")
    db.add(row)
    await db.commit()
    return {"id": row.id}


@router.put("/examples/{key}")
async def edit(key: str, body: ExampleInput, request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    row = await get_row(db, TrainingExample, key)
    row.data, row.status, row.reviewer = body.model_dump(), "draft", None
    await db.commit()
    return {"id": row.id, "status": row.status}


@router.delete("/examples/{key}")
async def delete(key: str, request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    await db.delete(await get_row(db, TrainingExample, key))
    await db.commit()
    return {"note": "Deleted from curation. Existing immutable exports are retained."}


@router.post("/examples/{key}/review")
async def review(key: str, body: ReviewInput, request: Request, db: AsyncSession = Depends(get_db)):
    user = require_admin(request)
    row = await get_row(db, TrainingExample, key)
    if body.status == "approved" and not row.data.get("rights_approved"):
        raise HTTPException(422, "Confirm training rights before approving.")
    row.status, row.reviewer = body.status, user.username
    await db.commit()
    return {"id": row.id, "status": row.status}


@router.post("/datasets", status_code=201)
async def freeze(body: DatasetInput, request: Request, db: AsyncSession = Depends(get_db)):
    user = require_admin(request)
    rows = (await db.execute(select(TrainingExample))).scalars().all()
    try:
        manifest = prepare_dataset(rows, model=body.base_model, revision=body.base_revision, license_note=body.license_note)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    row = TrainingDataset(manifest=manifest, created_by=user.username)
    db.add(row)
    await db.commit()
    return {"id": row.id, "dataset_hash": manifest["dataset_hash"]}


@router.get("/datasets/{key}/download")
async def download(key: str, request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    row = await get_row(db, TrainingDataset, key)
    return Response(json.dumps(row.manifest, ensure_ascii=False, indent=2), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="training-{row.id}.json"',
                             "Cache-Control": "no-store"})


@router.post("/datasets/{key}/evaluations", status_code=201)
async def evaluation(key: str, body: EvaluationInput, request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    row = await get_row(db, TrainingDataset, key)
    if len(json.dumps(body.report)) > 2_000_000:
        raise HTTPException(413, "Evaluation exceeds 2 MB")
    try:
        report = validate_report(row.manifest, body.report)
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    item = TrainingEvaluation(dataset_id=key, report=report)
    db.add(item)
    await db.commit()
    return {"id": item.id, "status": "needs_review"}


@router.post("/evaluations/{key}/review")
async def approve(key: str, body: ApprovalInput, request: Request, db: AsyncSession = Depends(get_db)):
    user = require_admin(request)
    if not body.checked_grounding_and_style:
        raise HTTPException(422, "Human review of grounding and style is required.")
    row = await get_row(db, TrainingEvaluation, key)
    row.status, row.review_note, row.reviewed_by = body.decision, body.note, user.username
    row.review_scores = body.scores
    await db.commit()
    return {"status": row.status, "note": "Review recorded only. Live inference has NOT changed."}