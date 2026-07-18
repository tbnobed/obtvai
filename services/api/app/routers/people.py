from fastapi import APIRouter, Depends, HTTPException, Query
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
    PersonSplitIn,
    ReanalyzeOut,
    PeoplePageOut,
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
        voice_preset=person.voice_preset,
        voice_settings=person.voice_settings,
    )


_STATS = (
    select(
        PersonAppearance.person_id,
        func.count(func.distinct(PersonAppearance.media_id)).label("assets"),
        func.coalesce(func.sum(PersonAppearance.speaking_seconds), 0).label("speaking"),
        func.coalesce(func.sum(PersonAppearance.segment_count), 0).label("segments"),
    ).group_by(PersonAppearance.person_id)
).subquery()


@router.get("", response_model=PeoplePageOut)
async def list_people(
    limit: int = Query(48, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    total = (await db.execute(select(func.count(Person.id)))).scalar_one()
    rows = (
        await db.execute(
            select(Person, _STATS.c.assets, _STATS.c.speaking, _STATS.c.segments)
            .outerjoin(_STATS, _STATS.c.person_id == Person.id)
            .order_by(
                func.coalesce(_STATS.c.assets, 0).desc(),
                func.coalesce(_STATS.c.speaking, 0).desc(),
                Person.created_at,
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return PeoplePageOut(
        items=[_person_out(p, a or 0, s or 0, g or 0) for p, a, s, g in rows],
        total=int(total or 0),
    )


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

    # Also serialize against in-flight identify workers before wiping people.
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('obtv_identify'))"))

    # Start identification from a clean slate: drop all auto-created people so
    # stale identities (e.g. over-merged "blob" people built under older, looser
    # similarity thresholds) can't keep absorbing speakers on the re-run.
    # Manually named people are kept — their embeddings still match future runs.
    await db.execute(
        delete(PersonAppearance).where(
            PersonAppearance.person_id.in_(
                select(Person.id).where(
                    (Person.name_source.is_(None)) | (Person.name_source != "manual")
                )
            )
        )
    )
    await db.execute(
        delete(Person).where(
            (Person.name_source.is_(None)) | (Person.name_source != "manual")
        )
    )

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
                    ProcessingJob.job_type.in_(("diarize", "scene_detect", "face_detect", "identify")),
                    ProcessingJob.status.in_(("pending", "running")),
                )
            )
        ).scalars().first()
        if active:
            continue

        # Assets processed before the start_in_scene fix can have ZERO scenes
        # (uncut talking-head footage) — face_detect then exits immediately
        # with "No scenes for face detection". Re-run scene_detect for those;
        # it chains into face_detect (and visual_embed) itself.
        has_scenes = (
            await db.execute(
                text("SELECT 1 FROM scenes WHERE media_id = :mid LIMIT 1"),
                {"mid": media_id},
            )
        ).first()

        queued_any = False
        for job_type in ("diarize", "face_detect" if has_scenes else "scene_detect"):
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
    name_changed = person.display_name != name
    person.display_name = name
    person.name_source = "manual"
    await db.commit()
    await db.refresh(person)
    if name_changed:
        # Rebuild the LLM bio under the new name (fire-and-forget).
        from ..worker_client import _publish
        import uuid as _uuid
        try:
            await _publish(
                "gpu", "tasks.identify.regenerate_profile",
                {"person_id": id}, str(_uuid.uuid4()),
            )
        except Exception:
            pass  # profile refresh is best-effort; rename itself already saved
    return _person_out(person, assets or 0, speaking or 0, segments or 0)


@router.delete("/{id}", status_code=204)
async def delete_person(id: str, db: AsyncSession = Depends(get_db)):
    """Remove a person entirely — for deleting false-positive detections.
    Cleans up appearances and voice-clone data (samples, generations, files)."""
    import os
    from sqlalchemy import text
    from ..models import VoiceSample, VoiceGeneration

    person = (await db.execute(select(Person).where(Person.id == id))).scalar_one_or_none()
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")

    # Same lock the identify worker holds, so a delete can't interleave with
    # an in-flight identification pass.
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('obtv_identify'))"))

    audio_files: list[str] = []
    for vs in (await db.execute(select(VoiceSample).where(VoiceSample.person_id == id))).scalars():
        audio_files += [p for p in (vs.audio_path, vs.raw_path) if p]
    for vg in (await db.execute(select(VoiceGeneration).where(VoiceGeneration.person_id == id))).scalars():
        if vg.audio_path:
            audio_files.append(vg.audio_path)

    await db.execute(delete(VoiceGeneration).where(VoiceGeneration.person_id == id))
    await db.execute(delete(VoiceSample).where(VoiceSample.person_id == id))
    await db.execute(delete(PersonAppearance).where(PersonAppearance.person_id == id))
    await db.execute(delete(Person).where(Person.id == id))
    await db.commit()

    for path in audio_files:
        try:
            os.remove(path)
        except OSError:
            pass


@router.post("/{id}/split", response_model=PersonOut)
async def split_person(id: str, body: PersonSplitIn, db: AsyncSession = Depends(get_db)):
    """Move one appearance out of a person into a brand-new person — the
    undo for a bad merge or a wrong automatic identification."""
    from sqlalchemy import text
    from ..models import FaceCluster, MediaAsset as MA

    # Same lock the identify worker holds, so a split can't interleave with
    # an in-flight identification pass.
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('obtv_identify'))"))

    person = (await db.execute(select(Person).where(Person.id == id))).scalar_one_or_none()
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    q = select(PersonAppearance).where(
        PersonAppearance.person_id == id,
        PersonAppearance.media_id == body.media_id,
    )
    if body.speaker_label is not None:
        q = q.where(PersonAppearance.speaker_label == body.speaker_label)
    if body.face_cluster_id is not None:
        q = q.where(PersonAppearance.face_cluster_id == body.face_cluster_id)
    appearance = (await db.execute(q)).scalars().first()
    if not appearance:
        raise HTTPException(status_code=404, detail="Appearance not found on this person")

    total_apps = (
        await db.execute(
            select(func.count(PersonAppearance.id)).where(PersonAppearance.person_id == id)
        )
    ).scalar_one()
    if total_apps <= 1:
        raise HTTPException(
            status_code=409,
            detail="This is the person's only appearance — rename this person instead of splitting",
        )

    # Rebuild identity signals for the new person from the source asset itself
    # (NOT from the old person's blended embeddings, which caused the bad merge).
    voice_emb = None
    if appearance.speaker_label:
        asset = (
            await db.execute(select(MA).where(MA.id == body.media_id))
        ).scalar_one_or_none()
        if asset and asset.speaker_embeddings:
            voice_emb = asset.speaker_embeddings.get(appearance.speaker_label)

    face_emb = None
    thumb = None
    if appearance.face_cluster_id:
        cluster = (
            await db.execute(
                select(FaceCluster).where(FaceCluster.cluster_id == appearance.face_cluster_id)
            )
        ).scalar_one_or_none()
        if cluster:
            face_emb = cluster.embedding
            thumb = cluster.thumbnail_url

    count = (await db.execute(select(func.count(Person.id)))).scalar_one()
    new_person = Person(
        display_name=f"Person {int(count or 0) + 1}",
        name_source=None,
        thumbnail_url=thumb,
        voice_embedding=voice_emb,
        face_embedding=face_emb,
    )
    db.add(new_person)
    await db.flush()
    appearance.person_id = new_person.id
    await db.commit()

    person_row, assets, speaking, segments = await _get_person_with_stats(new_person.id, db)
    return _person_out(person_row, assets or 0, speaking or 0, segments or 0)


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
