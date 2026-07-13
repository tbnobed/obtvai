from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from ..database import get_db
from ..models import Person, PersonAppearance, MediaAsset
from ..schemas import (
    PersonOut,
    PersonDetailOut,
    PersonAppearanceOut,
    PersonUpdateIn,
    PersonMergeIn,
    ReanalyzeOut,
)

router = APIRouter(prefix="/people", tags=["people"])


def _blend(a, b):
    """Average two embedding vectors and renormalize; tolerates missing sides."""
    if not a:
        return b
    if not b or len(a) != len(b):
        return a
    merged = [(x + y) / 2.0 for x, y in zip(a, b)]
    norm = sum(v * v for v in merged) ** 0.5
    if norm <= 0:
        return a
    return [v / norm for v in merged]


def _person_out(person: Person, asset_count: int, speaking: float, segments: int) -> PersonOut:
    return PersonOut(
        id=person.id,
        display_name=person.display_name,
        name_source=person.name_source,
        thumbnail_url=person.thumbnail_url,
        speech_style=person.speech_style,
        key_topics=person.key_topics or [],
        summary=person.summary,
        asset_count=asset_count,
        total_speaking_seconds=float(speaking or 0),
        segment_count=int(segments or 0),
        updated_at=person.updated_at,
    )


_STATS = (
    select(
        PersonAppearance.person_id,
        func.count(func.distinct(PersonAppearance.media_id)).label("assets"),
        func.coalesce(func.sum(PersonAppearance.speaking_seconds), 0).label("speaking"),
        func.coalesce(func.sum(PersonAppearance.segment_count), 0).label("segments"),
    ).group_by(PersonAppearance.person_id)
).subquery()


@router.get("", response_model=list[PersonOut])
async def list_people(db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(Person, _STATS.c.assets, _STATS.c.speaking, _STATS.c.segments)
            .outerjoin(_STATS, _STATS.c.person_id == Person.id)
            .order_by(
                func.coalesce(_STATS.c.assets, 0).desc(),
                func.coalesce(_STATS.c.speaking, 0).desc(),
            )
        )
    ).all()
    return [_person_out(p, a or 0, s or 0, g or 0) for p, a, s, g in rows]


@router.post("/reanalyze", response_model=ReanalyzeOut, status_code=202)
async def reanalyze_people(db: AsyncSession = Depends(get_db)):
    """Backfill person identification for media processed before the People
    system existed: re-runs diarization (voice embeddings) and face analysis
    (face cluster embeddings) on every ready asset, which chain into identify."""
    from sqlalchemy import text
    from ..models import ProcessingJob
    from .jobs import prune_finished_jobs
    from ..worker_client import enqueue_job

    # Serialize concurrent reanalyze requests: the lock is held until this
    # transaction commits, so a second caller waits and then sees the pending
    # jobs the first one created (its active-job check skips those assets).
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('obtv_reanalyze'))"))

    assets = (
        await db.execute(select(MediaAsset.id).where(MediaAsset.status == "ready"))
    ).scalars().all()

    assets_queued = 0
    jobs_created = 0
    pending: list[tuple[str, str, str]] = []

    for media_id in assets:
        active = (
            await db.execute(
                select(ProcessingJob.id).where(
                    ProcessingJob.media_id == media_id,
                    ProcessingJob.job_type.in_(("diarize", "face_detect", "identify")),
                    ProcessingJob.status.in_(("pending", "running")),
                )
            )
        ).scalars().first()
        if active:
            continue

        queued_any = False
        for job_type in ("diarize", "face_detect"):
            await prune_finished_jobs(db, media_id, job_type)
            job = ProcessingJob(media_id=media_id, job_type=job_type, status="pending", logs=[])
            db.add(job)
            await db.flush()
            pending.append((job_type, media_id, job.id))
            jobs_created += 1
            queued_any = True
        if queued_any:
            assets_queued += 1

    await db.commit()

    for job_type, media_id, job_id in pending:
        await enqueue_job(job_type, media_id, job_id)

    return ReanalyzeOut(assets_queued=assets_queued, jobs_created=jobs_created)


async def _get_person_with_stats(id: str, db: AsyncSession):
    row = (
        await db.execute(
            select(Person, _STATS.c.assets, _STATS.c.speaking, _STATS.c.segments)
            .outerjoin(_STATS, _STATS.c.person_id == Person.id)
            .where(Person.id == id)
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Person not found")
    return row


@router.get("/{id}", response_model=PersonDetailOut)
async def get_person(id: str, db: AsyncSession = Depends(get_db)):
    person, assets, speaking, segments = await _get_person_with_stats(id, db)
    app_rows = (
        await db.execute(
            select(PersonAppearance, MediaAsset)
            .join(MediaAsset, MediaAsset.id == PersonAppearance.media_id)
            .where(PersonAppearance.person_id == id)
            .order_by(MediaAsset.created_at.desc())
        )
    ).all()
    base = _person_out(person, assets or 0, speaking or 0, segments or 0)
    return PersonDetailOut(
        **base.model_dump(),
        appearances=[
            PersonAppearanceOut(
                media_id=asset.id,
                filename=asset.filename,
                thumbnail_url=asset.thumbnail_url,
                duration_seconds=asset.duration_seconds,
                speaker_label=pa.speaker_label,
                face_cluster_id=pa.face_cluster_id,
                speaking_seconds=pa.speaking_seconds,
                segment_count=pa.segment_count,
                first_spoken_at=pa.first_spoken_at,
            )
            for pa, asset in app_rows
        ],
    )


@router.patch("/{id}", response_model=PersonOut)
async def update_person(id: str, body: PersonUpdateIn, db: AsyncSession = Depends(get_db)):
    name = body.display_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="display_name must not be empty")
    person, assets, speaking, segments = await _get_person_with_stats(id, db)
    person.display_name = name
    person.name_source = "manual"
    await db.commit()
    await db.refresh(person)
    return _person_out(person, assets or 0, speaking or 0, segments or 0)


@router.post("/{id}/merge", response_model=PersonOut)
async def merge_person(id: str, body: PersonMergeIn, db: AsyncSession = Depends(get_db)):
    if body.source_person_id == id:
        raise HTTPException(status_code=400, detail="Cannot merge a person into themselves")
    target = (await db.execute(select(Person).where(Person.id == id))).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Person not found")
    source = (
        await db.execute(select(Person).where(Person.id == body.source_person_id))
    ).scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source person not found")

    # Serialize against the identify worker: same advisory lock it holds, so a
    # merge can never interleave with an in-flight identification pass. The
    # xact variant releases automatically on commit/rollback.
    from sqlalchemy import text, update as sa_update

    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('obtv_identify'))"))

    # Re-read both rows under the lock; identify may have pruned/changed them.
    target = (await db.execute(select(Person).where(Person.id == id))).scalar_one_or_none()
    source = (
        await db.execute(select(Person).where(Person.id == body.source_person_id))
    ).scalar_one_or_none()
    if not target or not source:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Person changed during merge — retry")

    await db.execute(
        sa_update(PersonAppearance)
        .where(PersonAppearance.person_id == source.id)
        .values(person_id=target.id)
    )
    if not target.thumbnail_url and source.thumbnail_url:
        target.thumbnail_url = source.thumbnail_url
    # Blend embeddings (average + renormalize) so the merged identity keeps
    # matching both original voices/faces in future identify runs, instead of
    # re-splitting the person the user just merged.
    target.face_embedding = _blend(target.face_embedding, source.face_embedding)
    target.voice_embedding = _blend(target.voice_embedding, source.voice_embedding)
    await db.execute(delete(Person).where(Person.id == source.id))
    await db.commit()

    person, assets, speaking, segments = await _get_person_with_stats(id, db)
    return _person_out(person, assets or 0, speaking or 0, segments or 0)
