"""Production Campaign Builder API.

Campaigns are editorial records around the existing Project model.  Execution
creates the same StoryJob, ReelJob, and GraphicsGeneration rows used by the
existing tools and then sends those rows through their existing queues.  No
campaign-specific worker or queue is introduced.
"""

import math
import uuid
import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import current_user
from ..campaign_execution import (
    execution_conflict,
    merge_media_ranges,
    selected_media_ids,
    selected_media_ranges,
)
from ..database import get_db
from ..models import (
    Campaign,
    CampaignDeliverable,
    GraphicsGeneration,
    MediaAsset,
    Project,
    ReelJob,
    StoryJob,
    User,
)
from ..schemas import (
    CampaignClip,
    CampaignCreate,
    CampaignDeliverableCreate,
    CampaignDeliverableEnvelope,
    CampaignDeliverableOut,
    CampaignDeliverableUpdate,
    CampaignEnvelope,
    CampaignExecute,
    CampaignJobReference,
    CampaignListEnvelope,
    CampaignOut,
    CampaignStatus,
    CampaignUpdate,
)
from ..services.llm import generate_response
from .. import worker_client
from .graphics import _get_object_info, _resolve_preset, check_graph
from .projects import touch_project


router = APIRouter(prefix="/campaigns", tags=["campaigns"])

_LLM_TIMEOUT_SECONDS = 15 * 60
_PUBLISHING_STALE_SECONDS = 10 * 60


class CampaignAPIError(HTTPException):
    """Campaign errors are rendered as the contract's structured envelope."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        *,
        code: str = "campaign_error",
        details: object | None = None,
    ):
        self.error_code = code
        self.error_message = detail
        self.error_details = details
        super().__init__(status_code=status_code, detail=detail)


async def _validate_clips(
    db: AsyncSession, clips: list[CampaignClip]
) -> list[dict]:
    """Validate timecodes against the actual source duration.

    A missing duration is an explicit error rather than an unbounded clip:
    campaign selections must be safe for later render dispatch.
    """

    ids = list(dict.fromkeys(c.media_id for c in clips))
    if not ids:
        return []
    assets = (
        await db.execute(select(MediaAsset).where(MediaAsset.id.in_(ids)))
    ).scalars().all()
    by_id = {a.id: a for a in assets}
    missing = [media_id for media_id in ids if media_id not in by_id]
    if missing:
        raise CampaignAPIError(
            status_code=422,
            detail=f"Unknown media asset(s): {', '.join(sorted(missing))}",
        )

    result: list[dict] = []
    for clip in clips:
        asset = by_id[clip.media_id]
        duration = asset.duration_seconds
        if duration is None or not math.isfinite(float(duration)) or duration < 0:
            raise CampaignAPIError(
                status_code=422,
                detail=f"Source duration is unavailable for media asset {clip.media_id}",
            )
        start, end = float(clip.start_time), float(clip.end_time)
        if start < 0 or end <= start or end > float(duration) + 1e-6:
            raise CampaignAPIError(
                status_code=422,
                detail=(
                    f"Clip {clip.media_id} ({start:g}-{end:g}) is outside "
                    f"the source duration ({float(duration):g}s)"
                ),
            )
        data = clip.model_dump()
        if not data.get("filename"):
            data["filename"] = asset.filename
        result.append(data)
    return result


async def _load_campaign(campaign_id: str, db: AsyncSession) -> Campaign:
    campaign = (
        await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    ).scalar_one_or_none()
    if campaign is None:
        raise CampaignAPIError(status_code=404, detail="Campaign not found")
    return campaign


async def _load_deliverable(
    campaign_id: str, deliverable_id: str, db: AsyncSession, *, lock: bool = False
) -> CampaignDeliverable:
    query = select(CampaignDeliverable).where(
        CampaignDeliverable.id == deliverable_id,
        CampaignDeliverable.campaign_id == campaign_id,
    )
    if lock:
        query = query.with_for_update()
    deliverable = (await db.execute(query)).scalar_one_or_none()
    if deliverable is None:
        raise CampaignAPIError(status_code=404, detail="Deliverable not found")
    return deliverable


def _campaign_prompt(campaign: Campaign, deliverable: CampaignDeliverable) -> str:
    parts = [
        f"Campaign: {campaign.name}",
        f"Brief: {campaign.brief}",
        f"Objective: {campaign.objective}",
        f"Audience: {campaign.audience}",
        f"Key message: {campaign.key_message}",
        f"Tone: {campaign.tone}",
        f"Call to action: {campaign.call_to_action}",
        f"Channel: {deliverable.channel}",
        f"Language: {deliverable.language}",
    ]
    if deliverable.notes:
        parts.append(f"Deliverable notes: {deliverable.notes}")
    return "\n".join(parts)


def _publishing_is_stale(deliverable: CampaignDeliverable) -> bool:
    if deliverable.dispatch_state == "ambiguous":
        return True
    if deliverable.dispatch_state != "publishing":
        return False
    if not deliverable.execution_started_at:
        return True
    return (
        datetime.utcnow() - deliverable.execution_started_at
    ).total_seconds() >= _PUBLISHING_STALE_SECONDS


def _dispatch_unknown_error(deliverable: CampaignDeliverable) -> str:
    return (
        deliverable.error
        or "Dispatch acknowledgement was lost; the linked Studio job may still "
        "start or complete. Inspect it before retrying."
    )


async def _job_state(
    deliverable: CampaignDeliverable, db: AsyncSession
) -> tuple[str, str | None, str | None, str | None]:
    """Return current status/output/error from the referenced real job."""

    reference = deliverable.job_reference or {}
    reference_type = reference.get("type")
    reference_id = reference.get("id")
    if not reference_type or not reference_id:
        return (
            deliverable.status,
            deliverable.output_url,
            deliverable.output_text,
            deliverable.error,
        )

    if reference_type == "story_job":
        job = (
            await db.execute(select(StoryJob).where(StoryJob.id == reference_id))
        ).scalar_one_or_none()
        if job is None:
            return "failed", None, None, "Referenced StoryJob no longer exists"
        if job.status in {"pending", "queued"}:
            if _publishing_is_stale(deliverable):
                return "dispatch_unknown", None, None, _dispatch_unknown_error(deliverable)
            return "queued", None, None, deliverable.error
        if job.status in {"running", "selecting"}:
            return "running", None, None, None
        if job.status == "success":
            # Story success is an editable clip-list/script draft, not a
            # rendered promo.  It is terminal but never claims final output.
            return "draft_ready", None, None, None
        if job.status in {"error", "failed", "cancelled"}:
            return "failed", None, None, job.error_message or "StoryJob failed"
        return "running", None, None, None

    if reference_type == "reel_job":
        job = (
            await db.execute(select(ReelJob).where(ReelJob.id == reference_id))
        ).scalar_one_or_none()
        if job is None:
            return "failed", None, None, "Referenced ReelJob no longer exists"
        if job.status in {"pending", "queued"}:
            if _publishing_is_stale(deliverable):
                return "dispatch_unknown", None, None, _dispatch_unknown_error(deliverable)
            return "queued", None, None, deliverable.error
        if job.status in {"running", "selecting"}:
            return "running", None, None, None
        if job.status == "draft":
            return "draft_ready", None, None, None
        if job.status == "success":
            if job.output_path:
                return "ready", f"/api/reels/{job.id}/download", None, None
            return "draft_ready", None, None, None
        if job.status in {"error", "failed", "cancelled"}:
            return "failed", None, None, job.error_message or "ReelJob failed"
        return "running", None, None, None

    if reference_type == "graphics_generation":
        job = (
            await db.execute(
                select(GraphicsGeneration).where(
                    GraphicsGeneration.id == reference_id
                )
            )
        ).scalar_one_or_none()
        if job is None:
            return "failed", None, None, "Referenced GraphicsGeneration no longer exists"
        if job.status in {"pending", "queued"}:
            if _publishing_is_stale(deliverable):
                return "dispatch_unknown", None, None, _dispatch_unknown_error(deliverable)
            return "queued", None, None, deliverable.error
        if job.status == "running":
            return "running", None, None, None
        if job.status == "success" and job.output_path:
            return "ready", f"/api/graphics/generations/{job.id}/output", None, None
        if job.status == "success":
            return "failed", None, None, "Graphics generation completed without output"
        if job.status in {"error", "failed", "cancelled"}:
            return "failed", None, None, job.error_message or "Graphics generation failed"
        return "running", None, None, None

    # LLM output is stored transactionally on the deliverable itself because
    # the existing helper has no separate job table.  If the process died while
    # awaiting a request, publishing remains distinguishable from a known
    # failure and is made explicit after a bounded timeout.
    if (
        reference_type == "llm_generation"
        and deliverable.status == "running"
        and deliverable.execution_started_at
        and (datetime.utcnow() - deliverable.execution_started_at).total_seconds()
        >= _LLM_TIMEOUT_SECONDS
    ):
        return (
            "failed",
            None,
            None,
            "LLM generation timed out or was interrupted; retry explicitly",
        )
    return (
        deliverable.status,
        deliverable.output_url,
        deliverable.output_text,
        deliverable.error,
    )


async def _deliverable_out(
    deliverable: CampaignDeliverable, db: AsyncSession
) -> CampaignDeliverableOut:
    # Persist terminal/confirmed reconciliation as well as returning it. This
    # turns stale publishing attempts into durable dispatch_unknown records
    # while allowing a later worker start/success to replace that warning.
    status, output_url, output_text, error = await _persist_derived_state(
        deliverable, db
    )
    return CampaignDeliverableOut(
        id=deliverable.id,
        campaign_id=deliverable.campaign_id,
        kind=deliverable.kind,
        label=deliverable.label,
        channel=deliverable.channel,
        language=deliverable.language,
        target_duration_seconds=deliverable.target_duration_seconds,
        aspect_ratio=deliverable.aspect_ratio,
        notes=deliverable.notes,
        status=status,
        job_reference=(
            CampaignJobReference.model_validate(deliverable.job_reference)
            if deliverable.job_reference
            else None
        ),
        output_url=output_url,
        output_text=output_text,
        error=error,
        created_at=deliverable.created_at,
        updated_at=deliverable.updated_at,
    )


async def _campaign_out(campaign: Campaign, db: AsyncSession) -> CampaignOut:
    rows = (
        await db.execute(
            select(CampaignDeliverable)
            .where(CampaignDeliverable.campaign_id == campaign.id)
            .order_by(CampaignDeliverable.created_at)
        )
    ).scalars().all()
    deliverables = [await _deliverable_out(row, db) for row in rows]
    return CampaignOut(
        id=campaign.id,
        project_id=campaign.project_id,
        name=campaign.name,
        brief=campaign.brief,
        objective=campaign.objective,
        audience=campaign.audience,
        key_message=campaign.key_message,
        tone=campaign.tone,
        call_to_action=campaign.call_to_action,
        channels=list(campaign.channels or []),
        languages=list(campaign.languages or []),
        due_date=campaign.due_date,
        status=campaign.status,
        selected_clips=[
            CampaignClip.model_validate(clip)
            for clip in (campaign.selected_clips or [])
        ],
        deliverables=deliverables,
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
    )


async def _persist_derived_state(
    deliverable: CampaignDeliverable, db: AsyncSession, *, commit: bool = True
) -> tuple[str, str | None, str | None, str | None]:
    state = await _job_state(deliverable, db)
    status, output_url, output_text, error = state
    changed = (
        deliverable.status != status
        or deliverable.output_url != output_url
        or deliverable.output_text != output_text
        or deliverable.error != error
    )
    if changed:
        deliverable.status = status
        deliverable.output_url = output_url
        deliverable.output_text = output_text
        deliverable.error = error
        if status in {"dispatch_unknown", "draft_ready", "ready", "failed"}:
            deliverable.execution_lock = None
        if (
            status == "failed"
            and (deliverable.job_reference or {}).get("type") == "llm_generation"
        ):
            deliverable.dispatch_state = "failed"
        deliverable.updated_at = datetime.utcnow()
        db.add(deliverable)
        if commit:
            await db.commit()
    return state


async def _sync_project_selection(
    db: AsyncSession, project: Project, clips: list[dict]
) -> None:
    # A project is the source pool for its campaign.  Preserve any existing
    # project pool and add the campaign's selected sources; this is
    # intentionally metadata-only and never deletes media or generation jobs.
    existing = list(project.media_ids or [])
    project.media_ids = list(dict.fromkeys(existing + selected_media_ids(clips)))
    project.media_ranges = (
        merge_media_ranges(project.media_ranges, selected_media_ranges(clips))
        or None
    )
    project.updated_at = datetime.utcnow()
    db.add(project)


@router.get(
    "",
    response_model=CampaignListEnvelope,
    operation_id="listCampaigns",
)
async def list_campaigns(
    status: CampaignStatus | None = None,
    project_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(current_user),
):
    query = select(Campaign).order_by(Campaign.created_at.desc())
    if status:
        query = query.where(Campaign.status == status.value)
    if project_id:
        query = query.where(Campaign.project_id == project_id)
    campaigns = (await db.execute(query)).scalars().all()
    return CampaignListEnvelope(
        data=[await _campaign_out(campaign, db) for campaign in campaigns]
    )


@router.post(
    "",
    response_model=CampaignEnvelope,
    status_code=201,
    operation_id="createCampaign",
)
async def create_campaign(
    body: CampaignCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    clips = await _validate_clips(db, body.selected_clips)
    if body.project_id:
        project = (
            await db.execute(select(Project).where(Project.id == body.project_id))
        ).scalar_one_or_none()
        if project is None:
            raise CampaignAPIError(status_code=404, detail="Project not found")
    else:
        project = Project(
            id=str(uuid.uuid4()),
            name=body.project_action.name.strip(),
            description=body.brief,
            media_ids=selected_media_ids(clips),
            created_at=datetime.utcnow(),
        )
        db.add(project)
        await db.flush()

    await _sync_project_selection(db, project, clips)
    campaign = Campaign(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name=body.name.strip(),
        brief=body.brief.strip(),
        objective=body.objective.strip(),
        audience=body.audience.strip(),
        key_message=body.key_message.strip(),
        tone=body.tone.strip(),
        call_to_action=body.call_to_action.strip(),
        channels=[channel.strip() for channel in body.channels],
        languages=[language.strip() for language in body.languages],
        due_date=body.due_date,
        status=body.status.value,
        selected_clips=clips,
        created_by=user.id,
        updated_by=user.id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return CampaignEnvelope(data=await _campaign_out(campaign, db))


@router.get(
    "/{campaign_id}",
    response_model=CampaignEnvelope,
    operation_id="getCampaign",
)
async def get_campaign(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(current_user),
):
    campaign = await _load_campaign(campaign_id, db)
    return CampaignEnvelope(data=await _campaign_out(campaign, db))


@router.patch(
    "/{campaign_id}",
    response_model=CampaignEnvelope,
    operation_id="updateCampaign",
)
async def update_campaign(
    campaign_id: str,
    body: CampaignUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    campaign = await _load_campaign(campaign_id, db)
    project = (
        await db.execute(select(Project).where(Project.id == campaign.project_id))
    ).scalar_one_or_none()
    if project is None:
        raise CampaignAPIError(status_code=409, detail="Linked project no longer exists")

    if "selected_clips" in body.model_fields_set:
        clips = await _validate_clips(db, body.selected_clips or [])
        campaign.selected_clips = clips
        await _sync_project_selection(db, project, clips)
    for field in (
        "name",
        "brief",
        "objective",
        "audience",
        "key_message",
        "tone",
        "call_to_action",
        "due_date",
        "status",
    ):
        if field not in body.model_fields_set:
            continue
        value = getattr(body, field)
        if field == "status" and value is not None:
            value = value.value
        if field == "name" and value is not None:
            value = value.strip()
        setattr(campaign, field, value)
    if "channels" in body.model_fields_set:
        campaign.channels = [value.strip() for value in (body.channels or [])]
    if "languages" in body.model_fields_set:
        campaign.languages = [value.strip() for value in (body.languages or [])]
    campaign.updated_by = user.id
    campaign.updated_at = datetime.utcnow()
    db.add(campaign)
    await touch_project(db, project.id)
    await db.commit()
    await db.refresh(campaign)
    return CampaignEnvelope(data=await _campaign_out(campaign, db))


@router.delete(
    "/{campaign_id}",
    status_code=204,
    operation_id="deleteCampaign",
)
async def delete_campaign(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(current_user),
):
    campaign = await _load_campaign(campaign_id, db)
    # The relationship cascade deletes campaign metadata only.  Project,
    # source media, and referenced generation jobs remain untouched.
    await db.delete(campaign)
    await db.commit()


@router.post(
    "/{campaign_id}/deliverables",
    response_model=CampaignDeliverableEnvelope,
    status_code=201,
    operation_id="createCampaignDeliverable",
)
async def create_campaign_deliverable(
    campaign_id: str,
    body: CampaignDeliverableCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    await _load_campaign(campaign_id, db)
    deliverable = CampaignDeliverable(
        id=str(uuid.uuid4()),
        campaign_id=campaign_id,
        kind=body.kind.value,
        label=body.label.strip(),
        channel=body.channel.strip(),
        language=body.language.strip(),
        target_duration_seconds=body.target_duration_seconds,
        aspect_ratio=body.aspect_ratio.strip(),
        notes=body.notes,
        status="pending",
        dispatch_state="not_started",
        created_by=user.id,
        updated_by=user.id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(deliverable)
    await db.commit()
    await db.refresh(deliverable)
    return CampaignDeliverableEnvelope(data=await _deliverable_out(deliverable, db))


@router.patch(
    "/{campaign_id}/deliverables/{deliverable_id}",
    response_model=CampaignDeliverableEnvelope,
    operation_id="updateCampaignDeliverable",
)
async def update_campaign_deliverable(
    campaign_id: str,
    deliverable_id: str,
    body: CampaignDeliverableUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    deliverable = await _load_deliverable(campaign_id, deliverable_id, db)
    if deliverable.job_reference and "kind" in body.model_fields_set:
        raise CampaignAPIError(
            status_code=409,
            detail="The kind cannot change after execution has created a job",
        )
    for field in (
        "kind",
        "label",
        "channel",
        "language",
        "target_duration_seconds",
        "aspect_ratio",
        "notes",
    ):
        if field not in body.model_fields_set:
            continue
        value = getattr(body, field)
        if field == "kind" and value is not None:
            value = value.value
        if field in {"label", "channel", "language", "aspect_ratio"} and value is not None:
            value = value.strip()
        setattr(deliverable, field, value)
    deliverable.updated_at = datetime.utcnow()
    deliverable.updated_by = user.id
    db.add(deliverable)
    await db.commit()
    await db.refresh(deliverable)
    return CampaignDeliverableEnvelope(data=await _deliverable_out(deliverable, db))


@router.delete(
    "/{campaign_id}/deliverables/{deliverable_id}",
    status_code=204,
    operation_id="deleteCampaignDeliverable",
)
async def delete_campaign_deliverable(
    campaign_id: str,
    deliverable_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(current_user),
):
    deliverable = await _load_deliverable(campaign_id, deliverable_id, db)
    await db.delete(deliverable)
    await db.commit()


async def _make_graphics_job(
    deliverable: CampaignDeliverable,
    campaign: Campaign,
    db: AsyncSession,
) -> GraphicsGeneration:
    preset_id = "flux-schnell"
    meta, graph, error = _resolve_preset(preset_id)
    if error or meta is None or graph is None:
        raise CampaignAPIError(
            status_code=503,
            detail=f"Thumbnail graphics preset unavailable: {error or 'unknown preset'}",
        )
    object_info, comfy_error = await _get_object_info(meta["kind"])
    if comfy_error:
        raise CampaignAPIError(status_code=503, detail=comfy_error)
    unavailable = check_graph(graph, object_info or {})
    if unavailable:
        raise CampaignAPIError(
            status_code=503,
            detail=f"Thumbnail graphics preset unavailable: {unavailable}",
        )

    dimensions = {
        "9:16": (576, 1024),
        "16:9": (1024, 576),
        "1:1": (1024, 1024),
    }
    width, height = dimensions.get(deliverable.aspect_ratio, (1024, 1024))
    media_id = None
    clips = campaign.selected_clips or []
    if clips:
        media_id = clips[0].get("media_id")
    generation = GraphicsGeneration(
        id=str(uuid.uuid4()),
        preset_id=preset_id,
        preset_name=meta["name"],
        kind=meta["kind"],
        prompt=_campaign_prompt(campaign, deliverable),
        width=width,
        height=height,
        steps=meta.get("default_steps"),
        status="pending",
        progress=0.0,
        params={"campaign_id": campaign.id, "deliverable_id": deliverable.id},
        media_id=media_id,
        created_at=datetime.utcnow(),
    )
    db.add(generation)
    return generation


@router.post(
    "/{campaign_id}/deliverables/{deliverable_id}/execute",
    response_model=CampaignDeliverableEnvelope,
    status_code=202,
    operation_id="executeCampaignDeliverable",
)
async def execute_campaign_deliverable(
    campaign_id: str,
    deliverable_id: str,
    body: CampaignExecute = CampaignExecute(),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    campaign = await _load_campaign(campaign_id, db)
    deliverable = await _load_deliverable(campaign_id, deliverable_id, db, lock=True)

    # Reconcile a persisted queued lock with the real job before deciding
    # whether this request is a duplicate or an explicit retry.
    # Keep the row lock held until the new reference and lock are committed.
    # This is what prevents two concurrent execute requests from dispatching
    # duplicate real jobs.
    await _persist_derived_state(deliverable, db, commit=False)
    conflict = execution_conflict(
        deliverable.status, deliverable.dispatch_state, body.retry
    )
    if conflict:
        raise CampaignAPIError(status_code=409, detail=conflict)

    if idempotency_key:
        idempotency_key = idempotency_key[:200]
        if (
            deliverable.idempotency_key == idempotency_key
            and deliverable.job_reference
        ):
            raise CampaignAPIError(
                status_code=409,
                detail="This idempotency key already dispatched the deliverable",
            )

    clips = campaign.selected_clips or []
    if deliverable.kind in {"promo", "reel"} and not clips:
        raise CampaignAPIError(
            status_code=422,
            detail=f"{deliverable.kind} execution requires at least one selected clip",
        )
    project = (
        await db.execute(select(Project).where(Project.id == campaign.project_id))
    ).scalar_one_or_none()
    if project is None:
        raise CampaignAPIError(status_code=409, detail="Linked project no longer exists")
    project_target = project.target_runtime_seconds
    target_duration = deliverable.target_duration_seconds
    if target_duration is None and project_target is not None:
        target_duration = min(max(float(project_target), 30.0), 14400.0)

    lock_id = str(uuid.uuid4())
    deliverable.execution_lock = lock_id
    deliverable.execution_started_at = datetime.utcnow()
    deliverable.execution_attempt = (deliverable.execution_attempt or 0) + 1
    deliverable.updated_by = user.id
    deliverable.idempotency_key = idempotency_key
    deliverable.dispatch_state = "publishing"
    deliverable.error = None
    deliverable.output_url = None
    deliverable.output_text = None

    job_reference: dict | None = None
    story: StoryJob | None = None
    reel: ReelJob | None = None
    graphics: GraphicsGeneration | None = None

    if deliverable.kind == "promo":
        story = StoryJob(
            id=str(uuid.uuid4()),
            prompt=_campaign_prompt(campaign, deliverable),
            project_id=campaign.project_id,
            asset_ids=selected_media_ids(clips),
            clip_ranges=clips,
            target_duration_seconds=target_duration,
            status="pending",
            progress=0.0,
            created_at=datetime.utcnow(),
        )
        db.add(story)
        job_reference = {"type": "story_job", "id": story.id}
    elif deliverable.kind == "reel":
        reel = ReelJob(
            id=str(uuid.uuid4()),
            prompt=_campaign_prompt(campaign, deliverable),
            media_id=clips[0].get("media_id") if len(selected_media_ids(clips)) == 1 else None,
            project_id=campaign.project_id,
            target_duration_seconds=target_duration,
            preset="vertical" if deliverable.aspect_ratio == "9:16" else "original",
            clips=clips,
            candidate_clips=clips,
            status="pending",
            progress=0.0,
            created_at=datetime.utcnow(),
        )
        db.add(reel)
        job_reference = {"type": "reel_job", "id": reel.id}
    elif deliverable.kind == "thumbnail":
        graphics = await _make_graphics_job(deliverable, campaign, db)
        job_reference = {"type": "graphics_generation", "id": graphics.id}
    elif deliverable.kind == "social_copy":
        job_reference = {"type": "llm_generation", "id": str(uuid.uuid4())}
    else:
        raise CampaignAPIError(status_code=422, detail="Unsupported deliverable kind")

    deliverable.job_reference = job_reference
    deliverable.status = "running" if deliverable.kind == "social_copy" else "queued"
    deliverable.updated_at = datetime.utcnow()
    db.add(deliverable)
    await touch_project(db, campaign.project_id)
    await db.commit()
    await db.refresh(deliverable)

    try:
        if story is not None:
            await worker_client.enqueue_story(story.id)
        elif reel is not None:
            await worker_client.enqueue_reel(reel.id, skip_curation=True)
        elif graphics is not None:
            await worker_client.enqueue_graphics(graphics.id)
        else:
            # The existing helper routes to configured remote LLM when
            # LLM_BASE_URL is set and otherwise uses the local model.  Errors
            # are deliberately surfaced; no heuristic/mock fallback exists.
            text = await asyncio.wait_for(
                generate_response(
                    _campaign_prompt(campaign, deliverable),
                    system=(
                        "Write production-ready social copy for the requested "
                        "campaign deliverable. Return only the copy in the target "
                        "language, with no preamble or claims unsupported by the brief."
                    ),
                    max_new_tokens=600,
                ),
                timeout=_LLM_TIMEOUT_SECONDS,
            )
            if not text.strip():
                raise RuntimeError("LLM returned empty social copy")
            deliverable.status = "ready"
            deliverable.output_text = text.strip()
            deliverable.error = None
            deliverable.execution_lock = None
            deliverable.dispatch_state = "published"
            deliverable.updated_at = datetime.utcnow()
            db.add(deliverable)
            await db.commit()
        if story is not None or reel is not None or graphics is not None:
            deliverable.dispatch_state = "published"
            deliverable.error = None
            deliverable.updated_at = datetime.utcnow()
            db.add(deliverable)
            await db.commit()
    except Exception as exc:
        # A queue publish exception is inherently ambiguous: Redis/Celery may
        # have accepted the message before the client observed the exception.
        # Keep the existing real-job identity and lock, never mark it failed,
        # and reject retries rather than risking a duplicate job.
        if story is not None or reel is not None or graphics is not None:
            deliverable.status = "dispatch_unknown"
            deliverable.dispatch_state = "ambiguous"
            deliverable.execution_lock = None
            deliverable.error = (
                "Dispatch outcome is unknown; the existing job may already be "
                f"queued. Do not retry this deliverable ({str(exc)[:1200]})"
            )
            deliverable.updated_at = datetime.utcnow()
            db.add(deliverable)
            await db.commit()
            raise CampaignAPIError(
                status_code=503,
                detail=deliverable.error,
            ) from exc

        # LLM failure is known because no external job was published. Persist a
        # terminal failure so callers receive an explicit, safely retryable 503.
        if story is not None:
            story.status = "error"
            story.error_message = str(exc)[:2000]
            story.finished_at = datetime.utcnow()
            db.add(story)
        if reel is not None:
            reel.status = "error"
            reel.error_message = str(exc)[:2000]
            reel.finished_at = datetime.utcnow()
            db.add(reel)
        if graphics is not None:
            graphics.status = "error"
            graphics.error_message = str(exc)[:2000]
            graphics.completed_at = datetime.utcnow()
            db.add(graphics)
        deliverable.status = "failed"
        deliverable.error = f"Execution failed: {str(exc)[:1800]}"
        deliverable.execution_lock = None
        deliverable.dispatch_state = "failed"
        deliverable.updated_at = datetime.utcnow()
        db.add(deliverable)
        await db.commit()
        raise CampaignAPIError(
            status_code=503,
            detail=deliverable.error,
        ) from exc

    return CampaignDeliverableEnvelope(data=await _deliverable_out(deliverable, db))