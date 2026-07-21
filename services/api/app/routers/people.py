from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from ..database import get_db
from ..models import Person, PersonAppearance, MediaAsset, TranscriptSegment, FaceCluster
from ..schemas import (
    PersonOut,
    PersonDetailOut,
    PersonAppearanceOut,
    PersonUpdateIn,
    ReprofileIn,
    PersonMergeIn,
    PersonSplitIn,
    PersonUnmergeIn,
    ReanalyzeOut,
    PeoplePageOut,
    PersonAssetMomentsOut,
    SpeakingMomentOut,
    OnCameraRangeOut,
    CoAppearanceGraphOut,
    CoAppearanceNodeOut,
    CoAppearancePairOut,
    PersonMatchOut,
    PersonEnrollOut,
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
        face_search=person.face_search,
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
    q: str | None = Query(None),
    sort: str = Query("appearances", pattern="^(appearances|name)$"),
    faces_only: bool | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    count_stmt = select(func.count(Person.id))
    stmt = select(Person, _STATS.c.assets, _STATS.c.speaking, _STATS.c.segments).outerjoin(
        _STATS, _STATS.c.person_id == Person.id
    )
    if faces_only:
        # Voice-only speakers (diarized but never face-matched, e.g. off-camera
        # crew) have no face embedding, no face-crop thumbnail, and no
        # face-cluster-linked appearance.
        face_filter = (
            Person.face_embedding.isnot(None)
            | Person.thumbnail_url.isnot(None)
            | select(PersonAppearance.id)
            .where(
                PersonAppearance.person_id == Person.id,
                PersonAppearance.face_cluster_id.isnot(None),
            )
            .exists()
        )
        count_stmt = count_stmt.where(face_filter)
        stmt = stmt.where(face_filter)
    if q and q.strip():
        needle = f"%{q.strip()}%"
        count_stmt = count_stmt.where(Person.display_name.ilike(needle))
        stmt = stmt.where(Person.display_name.ilike(needle))
    if sort == "name":
        stmt = stmt.order_by(func.lower(Person.display_name), Person.created_at)
    else:
        stmt = stmt.order_by(
            func.coalesce(_STATS.c.assets, 0).desc(),
            func.coalesce(_STATS.c.speaking, 0).desc(),
            Person.created_at,
        )
    total = (await db.execute(count_stmt)).scalar_one()
    rows = (await db.execute(stmt.limit(limit).offset(offset))).all()
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


ENROLL_MATCH_FLOOR = 0.25       # below this, faces are unrelated — hide entirely
ENROLL_STRONG_THRESHOLD = 0.50  # ArcFace same-person sims run 0.5-0.8; photo vs
                                # video-frame embeddings score a bit lower than
                                # frame vs frame, so "strong" sits slightly under
                                # the identify worker's 0.55 cluster threshold
ENROLL_MAX_MATCHES = 12


def _face_cosine(a, b) -> float:
    import numpy as np

    va, vb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if va.shape != vb.shape:
        return 0.0
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na <= 0 or nb <= 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


@router.post("/enroll", response_model=PersonEnrollOut, status_code=201)
async def enroll_person(
    photo: UploadFile = File(...),
    display_name: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Create a person from a reference photo: detect the most prominent face,
    store its ArcFace signature (future identify runs then auto-match new
    footage to this name), and return existing people whose stored face
    signatures resemble the photo — candidates the user can merge in."""
    import os
    import uuid as _uuid
    from fastapi.concurrency import run_in_threadpool
    from sqlalchemy import text
    from ..config import settings
    from ..face_enroll import decode_photo, extract_face, MAX_PHOTO_BYTES

    name = display_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="display_name must not be empty")
    data = await photo.read()
    if not data:
        raise HTTPException(status_code=422, detail="Empty photo upload")
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="Photo too large (15 MB max)")

    try:
        img = await run_in_threadpool(decode_photo, data)
    except Exception:
        raise HTTPException(status_code=422, detail="Could not read the image file")
    # Model/runtime failures (first-run download, onnxruntime) get a clear
    # 503 detail instead of being masked as a bad image or an opaque 500.
    try:
        emb, crop = await run_in_threadpool(extract_face, img)
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Face model failed to load or run: {type(e).__name__}: {e}",
        )
    if emb is None or crop is None:
        raise HTTPException(status_code=422, detail="No face detected in the photo")

    os.makedirs(settings.thumbnails_dir, exist_ok=True)
    thumb_name = f"person_enroll_{_uuid.uuid4().hex}.jpg"
    with open(os.path.join(settings.thumbnails_dir, thumb_name), "wb") as f:
        f.write(crop)

    # Same lock the identify worker holds, so enrollment can't interleave with
    # an in-flight identification pass.
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('obtv_identify'))"))

    person = Person(
        display_name=name,
        name_source="manual",
        thumbnail_url=thumb_name,
        face_embedding=emb,
    )
    db.add(person)
    await db.flush()

    candidates = (
        await db.execute(
            select(Person, _STATS.c.assets)
            .outerjoin(_STATS, _STATS.c.person_id == Person.id)
            .where(Person.id != person.id, Person.face_embedding.isnot(None))
        )
    ).all()
    matches: list[PersonMatchOut] = []
    for p, a in candidates:
        sim = _face_cosine(emb, p.face_embedding)
        if sim >= ENROLL_MATCH_FLOOR:
            matches.append(
                PersonMatchOut(
                    person_id=p.id,
                    display_name=p.display_name,
                    thumbnail_url=p.thumbnail_url,
                    asset_count=int(a or 0),
                    similarity=round(sim, 3),
                    strong=sim >= ENROLL_STRONG_THRESHOLD,
                )
            )
    matches.sort(key=lambda m: -m.similarity)
    await db.commit()

    person_row, assets, speaking, segments = await _get_person_with_stats(person.id, db)
    return PersonEnrollOut(
        person=_person_out(person_row, assets or 0, speaking or 0, segments or 0),
        matches=matches[:ENROLL_MAX_MATCHES],
    )


def _merge_intervals(raw: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for start, end in sorted(raw):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]


def _interval_overlap(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> float:
    """Total overlap between two sorted, merged interval lists (two-pointer)."""
    total = 0.0
    i = j = 0
    while i < len(a) and j < len(b):
        start = max(a[i][0], b[j][0])
        end = min(a[i][1], b[j][1])
        if end > start:
            total += end - start
        if a[i][1] <= b[j][1]:
            i += 1
        else:
            j += 1
    return total


MAX_CO_APPEARANCE_PAIRS = 300


# NOTE: must be registered before the /{id} routes below, or FastAPI would
# treat "co-appearances" as a person id.
@router.get("/co-appearances", response_model=CoAppearanceGraphOut)
async def get_co_appearances(
    named_only: bool = False,
    min_shared: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
):
    """Who appears together on camera: every pair of people sharing at least
    one asset, plus the seconds both are visibly on camera at the same time
    (computed from overlapping face-cluster appearance ranges).

    named_only restricts the graph to people with a real name (enrolled,
    renamed, or auto-recognized) so unnamed "Person N" / speaker-label
    placeholders don't flood the map; min_shared drops connections weaker
    than N shared videos."""
    people_query = select(Person, _STATS.c.assets).outerjoin(
        _STATS, _STATS.c.person_id == Person.id
    )
    if named_only:
        # Real names only (enrolled, renamed, or auto-recognized) — hides
        # "Person N" / raw speaker-label placeholders, whose name_source is NULL.
        people_query = people_query.where(Person.name_source.isnot(None))
    people_rows = (await db.execute(people_query)).all()
    known_ids = {p.id for p, _ in people_rows}

    rows = (
        await db.execute(
            select(
                PersonAppearance.person_id,
                PersonAppearance.media_id,
                PersonAppearance.face_cluster_id,
            )
        )
    ).all()
    # Filter appearances before pair-building so the pair cap budgets only the
    # people that will actually be drawn.
    rows = [r for r in rows if r[0] in known_ids]

    by_media: dict[str, set[str]] = {}
    clusters_of: dict[tuple[str, str], set[str]] = {}
    for pid, mid, cid in rows:
        by_media.setdefault(mid, set()).add(pid)
        if cid:
            clusters_of.setdefault((mid, pid), set()).add(cid)

    pair_assets: dict[tuple[str, str], int] = {}
    for mid, pids in by_media.items():
        ordered = sorted(pids)
        for i in range(len(ordered)):
            for j in range(i + 1, len(ordered)):
                key = (ordered[i], ordered[j])
                pair_assets[key] = pair_assets.get(key, 0) + 1

    # On-camera intervals per (asset, person) — only for assets shared by 2+
    # people, from the face clusters the identify pass attached to each person.
    shared_media = [mid for mid, pids in by_media.items() if len(pids) >= 2]
    intervals: dict[tuple[str, str], list[tuple[float, float]]] = {}
    if shared_media:
        fc_rows = (
            await db.execute(
                select(FaceCluster.media_id, FaceCluster.cluster_id, FaceCluster.appearances)
                .where(FaceCluster.media_id.in_(shared_media))
            )
        ).all()
        fc_map = {(m, c): a for m, c, a in fc_rows}
        for (mid, pid), cids in clusters_of.items():
            if len(by_media.get(mid) or ()) < 2:
                continue
            raw: list[tuple[float, float]] = []
            for cid in cids:
                for a in fc_map.get((mid, cid)) or []:
                    try:
                        raw.append((float(a["start_time"]), float(a["end_time"])))
                    except (KeyError, TypeError, ValueError):
                        continue
            if raw:
                intervals[(mid, pid)] = _merge_intervals(raw)

    together: dict[tuple[str, str], float] = {}
    for mid, pids in by_media.items():
        ordered = sorted(pids)
        for i in range(len(ordered)):
            for j in range(i + 1, len(ordered)):
                ia = intervals.get((mid, ordered[i]))
                ib = intervals.get((mid, ordered[j]))
                if ia and ib:
                    key = (ordered[i], ordered[j])
                    together[key] = together.get(key, 0.0) + _interval_overlap(ia, ib)

    if min_shared > 1:
        pair_assets = {k: n for k, n in pair_assets.items() if n >= min_shared}

    ranked = sorted(
        pair_assets.items(),
        key=lambda kv: (-kv[1], -together.get(kv[0], 0.0)),
    )
    # Guarantee every person keeps their strongest link before the cap trims
    # the rest — otherwise interview-style pairs (same asset, never in frame
    # together, so zero overlap seconds) are the first to be cut and the
    # interviewer looks unconnected.
    strongest: set[tuple[str, str]] = set()
    seen_people: set[str] = set()
    for key, _ in ranked:
        a, b = key
        if a not in seen_people or b not in seen_people:
            strongest.add(key)
        seen_people.add(a)
        seen_people.add(b)
    top_pairs = [kv for kv in ranked if kv[0] in strongest]
    budget = MAX_CO_APPEARANCE_PAIRS - len(top_pairs)
    if budget > 0:
        for kv in ranked:
            if kv[0] not in strongest:
                top_pairs.append(kv)
                budget -= 1
                if budget == 0:
                    break
        top_pairs.sort(key=lambda kv: (-kv[1], -together.get(kv[0], 0.0)))

    # Every person passing the filter is a node — including people who never
    # share a video with anyone (they render unconnected on the map).
    return CoAppearanceGraphOut(
        nodes=[
            CoAppearanceNodeOut(
                person_id=p.id,
                display_name=p.display_name,
                thumbnail_url=p.thumbnail_url,
                asset_count=int(a or 0),
            )
            for p, a in people_rows
        ],
        pairs=[
            CoAppearancePairOut(
                person_a_id=a,
                person_b_id=b,
                shared_assets=n,
                together_seconds=round(together.get((a, b), 0.0), 1),
            )
            for (a, b), n in top_pairs
            if a in known_ids and b in known_ids
        ],
    )


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
                merged_from=pa.merged_from,
            )
            for pa, asset in app_rows
        ],
    )


@router.get("/{id}/appearances/{media_id}", response_model=PersonAssetMomentsOut)
async def get_person_asset_moments(id: str, media_id: str, db: AsyncSession = Depends(get_db)):
    """Every timecoded place a person appears in one asset."""
    pa_rows = (
        await db.execute(
            select(PersonAppearance).where(
                PersonAppearance.person_id == id,
                PersonAppearance.media_id == media_id,
            )
        )
    ).scalars().all()
    if not pa_rows:
        raise HTTPException(status_code=404, detail="No appearance for this person in this asset")

    speakers = {pa.speaker_label for pa in pa_rows if pa.speaker_label}
    cluster_ids = {pa.face_cluster_id for pa in pa_rows if pa.face_cluster_id}

    speaking: list[SpeakingMomentOut] = []
    if speakers:
        segs = (
            await db.execute(
                select(TranscriptSegment)
                .where(
                    TranscriptSegment.media_id == media_id,
                    TranscriptSegment.speaker.in_(speakers),
                )
                .order_by(TranscriptSegment.start_time)
            )
        ).scalars().all()
        speaking = [
            SpeakingMomentOut(start_time=s.start_time, end_time=s.end_time, text=s.text)
            for s in segs
        ]

    on_camera: list[OnCameraRangeOut] = []
    if cluster_ids:
        clusters = (
            await db.execute(
                select(FaceCluster).where(
                    FaceCluster.cluster_id.in_(cluster_ids),
                    FaceCluster.media_id == media_id,
                )
            )
        ).scalars().all()
        ranges = []
        for c in clusters:
            for a in c.appearances or []:
                try:
                    ranges.append((float(a["start_time"]), float(a["end_time"])))
                except (KeyError, TypeError, ValueError):
                    continue
        for start, end in sorted(ranges):
            if on_camera and start <= on_camera[-1].end_time:
                on_camera[-1].end_time = max(on_camera[-1].end_time, end)
            else:
                on_camera.append(OnCameraRangeOut(start_time=start, end_time=end))

    return PersonAssetMomentsOut(media_id=media_id, speaking=speaking, on_camera=on_camera)


@router.patch("/{id}", response_model=PersonOut)
async def update_person(id: str, body: PersonUpdateIn, db: AsyncSession = Depends(get_db)):
    if body.display_name is None and body.summary is None:
        raise HTTPException(status_code=422, detail="Provide display_name and/or summary")
    person, assets, speaking, segments = await _get_person_with_stats(id, db)
    name_changed = False
    if body.display_name is not None:
        name = body.display_name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="display_name must not be empty")
        name_changed = person.display_name != name
        person.display_name = name
        person.name_source = "manual"
    if body.summary is not None:
        person.summary = body.summary.strip()[:2000] or None
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


@router.post("/{id}/reprofile", status_code=202)
async def reprofile_person(
    id: str,
    body: ReprofileIn | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Re-run the AI profile (bio / speech style / key topics) for one person."""
    person = (await db.execute(select(Person).where(Person.id == id))).scalar_one_or_none()
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    from ..worker_client import _publish
    import uuid as _uuid
    await _publish(
        "gpu", "tasks.identify.regenerate_profile",
        {"person_id": id, "use_web": bool(body and body.use_web)}, str(_uuid.uuid4()),
    )
    return None


@router.post("/{id}/photo", response_model=PersonOut)
async def update_person_photo(
    id: str,
    photo: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Replace this person's picture with an uploaded photo. If a face is
    detected it is cropped the same way enroll does; otherwise the whole image
    is used (voice-over talent never appears on camera). The stored
    face-matching signature is NOT touched — identification behavior stays
    exactly as before, only the displayed picture changes."""
    import os
    import uuid as _uuid
    from fastapi.concurrency import run_in_threadpool
    from ..config import settings
    from ..face_enroll import decode_photo, extract_face, whole_image_jpeg, MAX_PHOTO_BYTES

    person = (await db.execute(select(Person).where(Person.id == id))).scalar_one_or_none()
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    data = await photo.read()
    if not data:
        raise HTTPException(status_code=422, detail="Empty photo upload")
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="Photo too large (15 MB max)")
    try:
        img = await run_in_threadpool(decode_photo, data)
    except Exception:
        raise HTTPException(status_code=422, detail="Could not read the image file")
    # Face crop is only cosmetic here — if no face is found (or the face
    # model is unavailable) fall back to the whole image, center-cropped
    # square. Voice-over people never appear on camera.
    crop = None
    try:
        _, crop = await run_in_threadpool(extract_face, img)
    except Exception:
        pass
    if crop is None:
        crop = await run_in_threadpool(whole_image_jpeg, img)

    os.makedirs(settings.thumbnails_dir, exist_ok=True)
    thumb_name = f"person_photo_{_uuid.uuid4().hex}.jpg"
    with open(os.path.join(settings.thumbnails_dir, thumb_name), "wb") as f:
        f.write(crop)

    old = person.thumbnail_url
    person.thumbnail_url = thumb_name
    await db.commit()

    # Best-effort cleanup of a previous manually-uploaded photo (never touch
    # cluster thumbnails — they are shared with face clusters).
    if old and old.startswith("person_photo_"):
        try:
            os.remove(os.path.join(settings.thumbnails_dir, os.path.basename(old)))
        except OSError:
            pass

    person_row, assets, speaking, segments = await _get_person_with_stats(id, db)
    return _person_out(person_row, assets or 0, speaking or 0, segments or 0)


@router.delete("/{id}/photo", response_model=PersonOut)
async def delete_person_photo(id: str, db: AsyncSession = Depends(get_db)):
    """Clear this person's picture so the placeholder icon shows instead.
    Face-matching signatures are not touched."""
    import os
    from ..config import settings

    person = (await db.execute(select(Person).where(Person.id == id))).scalar_one_or_none()
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    old = person.thumbnail_url
    person.thumbnail_url = None
    await db.commit()

    # Only delete manually-uploaded photo files — cluster thumbnails are
    # shared with face clusters.
    if old and old.startswith("person_photo_"):
        try:
            os.remove(os.path.join(settings.thumbnails_dir, os.path.basename(old)))
        except OSError:
            pass

    person_row, assets, speaking, segments = await _get_person_with_stats(id, db)
    return _person_out(person_row, assets or 0, speaking or 0, segments or 0)


@router.post("/{id}/face-search", status_code=202)
async def face_search_person(id: str, db: AsyncSession = Depends(get_db)):
    """Queue a reverse web face search (Google Lens via SerpAPI) for this person.

    The person's face thumbnail is uploaded to a short-lived public host so
    Google Lens can fetch it — this is the only feature that sends media
    outside the network, and it only runs on explicit user request."""
    person = (await db.execute(select(Person).where(Person.id == id))).scalar_one_or_none()
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    if not person.thumbnail_url:
        raise HTTPException(status_code=409, detail="Person has no face thumbnail to search with")
    from datetime import datetime, timezone
    person.face_search = {"status": "pending", "queued_at": datetime.now(timezone.utc).isoformat()}
    await db.commit()
    from ..worker_client import _publish
    import uuid as _uuid
    await _publish(
        "cpu", "tasks.identify.face_search",
        {"person_id": id}, str(_uuid.uuid4()),
    )
    return None


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

    # Stamp merge provenance BEFORE re-parenting so every moved appearance
    # remembers who it belonged to (unmerge relies on this). Rows that already
    # carry provenance from an earlier merge keep their original owner.
    await db.execute(
        sa_update(PersonAppearance)
        .where(
            PersonAppearance.person_id == source.id,
            PersonAppearance.merged_from.is_(None),
        )
        .values(
            merged_from={
                "person_id": source.id,
                "display_name": source.display_name,
                "name_source": source.name_source,
            }
        )
    )
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


def _avg_norm(vectors: list) -> list | None:
    """Average a list of embedding vectors and renormalize; skips mismatched
    lengths (keyed off the first vector) and returns None when nothing usable."""
    vecs = [v for v in vectors if v]
    if not vecs:
        return None
    dim = len(vecs[0])
    vecs = [v for v in vecs if len(v) == dim]
    avg = [sum(col) / len(vecs) for col in zip(*vecs)]
    norm = sum(v * v for v in avg) ** 0.5
    if norm <= 0:
        return None
    return [v / norm for v in avg]


async def _identity_from_appearances(apps, db: AsyncSession):
    """Rebuild voice/face embeddings + thumbnail from appearances' source
    assets (speaker embeddings per diarized label, face-cluster embeddings) —
    never from blended person embeddings, which is what causes bad merges to
    stick. Returns (voice_embedding, face_embedding, thumbnail_url)."""
    media_ids = {a.media_id for a in apps}
    assets = {}
    if media_ids:
        assets = {
            m.id: m
            for m in (
                await db.execute(select(MediaAsset).where(MediaAsset.id.in_(media_ids)))
            ).scalars()
        }
    cluster_ids = [a.face_cluster_id for a in apps if a.face_cluster_id]
    clusters = {}
    if cluster_ids:
        clusters = {
            c.cluster_id: c
            for c in (
                await db.execute(
                    select(FaceCluster).where(FaceCluster.cluster_id.in_(cluster_ids))
                )
            ).scalars()
        }

    voice_embs: list = []
    face_embs: list = []
    thumb: str | None = None
    for a in apps:
        if a.speaker_label:
            asset = assets.get(a.media_id)
            if asset and asset.speaker_embeddings:
                emb = asset.speaker_embeddings.get(a.speaker_label)
                if emb:
                    voice_embs.append(emb)
        if a.face_cluster_id:
            cluster = clusters.get(a.face_cluster_id)
            if cluster:
                if cluster.embedding:
                    face_embs.append(cluster.embedding)
                if not thumb and cluster.thumbnail_url:
                    thumb = cluster.thumbnail_url
    return _avg_norm(voice_embs), _avg_norm(face_embs), thumb


@router.post("/{id}/unmerge", response_model=PersonOut)
async def unmerge_person(id: str, body: PersonUnmergeIn, db: AsyncSession = Depends(get_db)):
    """Undo a merge: every appearance stamped with merged_from=<person> moves
    back out into a restored person carrying the original name. Identity
    signals are rebuilt from the source assets themselves (not the blended
    embeddings the merge created)."""
    from sqlalchemy import text

    # Same lock the identify worker holds, so an unmerge can't interleave
    # with an in-flight identification pass.
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('obtv_identify'))"))

    person = (await db.execute(select(Person).where(Person.id == id))).scalar_one_or_none()
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    apps = (
        (
            await db.execute(
                select(PersonAppearance).where(
                    PersonAppearance.person_id == id,
                    PersonAppearance.merged_from["person_id"].astext
                    == body.merged_from_person_id,
                )
            )
        )
        .scalars()
        .all()
    )
    if not apps:
        raise HTTPException(
            status_code=404,
            detail="No appearances from that merge remain on this person",
        )

    info = apps[0].merged_from or {}

    # Rebuild the restored person's identity signals from the source assets so
    # future identify runs match them — never from the target's blended
    # embeddings, which is what caused the bad merge to stick.
    voice_emb, face_emb, thumb = await _identity_from_appearances(apps, db)

    restored = Person(
        display_name=info.get("display_name") or "Restored person",
        name_source=info.get("name_source"),
        thumbnail_url=thumb,
        voice_embedding=voice_emb,
        face_embedding=face_emb,
    )
    db.add(restored)
    await db.flush()
    for a in apps:
        a.person_id = restored.id
        a.merged_from = None

    # The merge blended the removed person's voice/face into the target's
    # embeddings; rebuild the target from its remaining appearances so identify
    # runs don't silently re-absorb the restored person later. Keep the old
    # embedding when the rebuild yields nothing usable (e.g. enrollment-only
    # people with no diarized/face-clustered footage).
    remaining = (
        (
            await db.execute(
                select(PersonAppearance).where(PersonAppearance.person_id == id)
            )
        )
        .scalars()
        .all()
    )
    if remaining:
        t_voice, t_face, _ = await _identity_from_appearances(remaining, db)
        if t_voice:
            person.voice_embedding = t_voice
        if t_face:
            person.face_embedding = t_face
    await db.commit()

    person_row, assets_n, speaking, segments = await _get_person_with_stats(restored.id, db)
    return _person_out(person_row, assets_n or 0, speaking or 0, segments or 0)
