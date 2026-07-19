import os
import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, delete, text
from ..database import get_db
from ..models import MediaAsset, Scene, TranscriptSegment, FaceCluster, ProcessingJob, Person, PersonAppearance
from ..schemas import (
    MediaAssetOut, MediaListResponse, MediaIngestInput,
    LibraryStats, SceneOut, TranscriptSegmentOut, FaceClusterOut, FaceAppearance,
    ProcessingJobOut, TranslateRequest, DubRequest,
    SocialCutsRequestIn, RenderJobOut,
    ClipExportResult, TightenInput, TightenCut, TightenResult,
    RoughCutInput, ReelJobOut, ResumeStalledOut,
    MarkerOut, MarkerInput,
    AssetPersonOut, SpeakingMomentOut, OnCameraRangeOut,
)
from ..models import ClipList, Clip, ReelJob
from ..config import settings
import redis.asyncio as aioredis

router = APIRouter(prefix="/media", tags=["media"])


def redis_client():
    return aioredis.from_url(settings.redis_url)


@router.get("/stats/summary", response_model=LibraryStats)
async def get_library_stats(db: AsyncSession = Depends(get_db)):
    total_q = await db.execute(select(func.count(MediaAsset.id)))
    total = total_q.scalar() or 0

    duration_q = await db.execute(select(func.sum(MediaAsset.duration_seconds)))
    total_duration = float(duration_q.scalar() or 0)

    # Duration of assets whose speech is actually searchable (they have
    # transcript segments) — the reconciled figure shown on the Dashboard
    # and Insights pages.
    speech_q = await db.execute(
        select(func.coalesce(func.sum(MediaAsset.duration_seconds), 0)).where(
            MediaAsset.id.in_(select(func.distinct(TranscriptSegment.media_id)))
        )
    )
    speech_indexed = float(speech_q.scalar() or 0)

    storage_q = await db.execute(select(func.sum(MediaAsset.file_size_bytes)))
    storage_bytes = int(storage_q.scalar() or 0)

    status_q = await db.execute(
        select(MediaAsset.status, func.count(MediaAsset.id)).group_by(MediaAsset.status)
    )
    status_counts = {row[0]: row[1] for row in status_q.all()}

    recent_q = await db.execute(
        select(MediaAsset).order_by(desc(MediaAsset.created_at)).limit(5)
    )
    recent = recent_q.scalars().all()

    return LibraryStats(
        total_assets=total,
        total_duration_seconds=total_duration,
        speech_indexed_seconds=speech_indexed,
        status_counts=status_counts,
        storage_bytes=storage_bytes,
        recent_activity=[MediaAssetOut.model_validate(a) for a in recent],
    )


@router.post("/resume-stalled", response_model=ResumeStalledOut, status_code=202)
async def resume_stalled_media(db: AsyncSession = Depends(get_db)):
    """Re-queue the missing pipeline stages for assets stranded mid-processing
    (e.g. their jobs were lost/cleared after an infra outage). For each asset
    not ready/error with no pending or running jobs, inspect what outputs
    already exist and queue only the producing stages that are missing. If
    nothing is missing, the asset is marked ready."""
    from sqlalchemy import text as sa_text
    from ..models import ProcessingJob
    from .jobs import prune_finished_jobs
    from ..worker_client import enqueue_job

    await db.execute(sa_text("SELECT pg_advisory_xact_lock(hashtext('obtv_resume'))"))

    stalled = (
        await db.execute(
            select(MediaAsset).where(
                MediaAsset.status.in_(("pending", "processing")),
                ~MediaAsset.id.in_(
                    select(ProcessingJob.media_id).where(
                        ProcessingJob.status.in_(("pending", "running")),
                        ProcessingJob.media_id.isnot(None),
                    )
                ),
            )
        )
    ).scalars().all()

    assets_resumed = 0
    jobs_created = 0
    assets_marked_ready = 0
    pending: list[tuple[str, str, str]] = []

    for asset in stalled:
        media_id = asset.id

        if asset.status == "pending":
            # Ingest never ran (or its queue message was lost): restart the pipeline.
            job_types = ["ingest"]
        else:
            transcript = (
                await db.execute(
                    sa_text(
                        "SELECT COUNT(*), COUNT(*) FILTER (WHERE embedding_id IS NULL) "
                        "FROM transcript_segments WHERE media_id = :mid"
                    ),
                    {"mid": media_id},
                )
            ).first()
            scenes = (
                await db.execute(
                    sa_text(
                        "SELECT COUNT(*), COUNT(*) FILTER (WHERE embedding_id IS NULL) "
                        "FROM scenes WHERE media_id = :mid"
                    ),
                    {"mid": media_id},
                )
            ).first()
            has_faces = (
                await db.execute(
                    sa_text("SELECT 1 FROM face_clusters WHERE media_id = :mid LIMIT 1"),
                    {"mid": media_id},
                )
            ).first()

            job_types = []
            if not asset.proxy_path:
                job_types.append("proxy")
            if transcript[0] == 0:
                # No transcript at all: restart from audio extraction, which
                # chains transcribe -> diarize + index downstream.
                job_types.append("audio_extract")
            elif transcript[1] > 0:
                job_types.append("index")
            if scenes[0] == 0:
                # scene_detect chains visual_embed + face_detect downstream.
                job_types.append("scene_detect")
            else:
                if scenes[1] > 0:
                    job_types.append("visual_embed")
                if not has_faces:
                    job_types.append("face_detect")

            if not job_types:
                asset.status = "ready"
                asset.processing_stage = "complete"
                asset.processing_progress = 100.0
                assets_marked_ready += 1
                continue

        for job_type in job_types:
            await prune_finished_jobs(db, media_id, job_type)
            job = ProcessingJob(media_id=media_id, job_type=job_type, status="pending", logs=[])
            db.add(job)
            await db.flush()
            pending.append((job_type, media_id, job.id))
            jobs_created += 1
        assets_resumed += 1

    await db.commit()

    for job_type, media_id, job_id in pending:
        try:
            await enqueue_job(job_type, media_id, job_id)
        except Exception as e:
            # Don't leave the job stranded as "pending" with no queue message —
            # mark it error so it's picked up by Retry All Failed.
            from sqlalchemy import update as sa_update
            await db.execute(
                sa_update(ProcessingJob)
                .where(ProcessingJob.id == job_id)
                .values(status="error", error_message=f"enqueue failed: {e}")
            )
            await db.commit()

    return ResumeStalledOut(
        assets_resumed=assets_resumed,
        jobs_created=jobs_created,
        assets_marked_ready=assets_marked_ready,
    )


@router.get("/{id}/markers", response_model=list[MarkerOut])
async def list_markers(id: str, db: AsyncSession = Depends(get_db)):
    from ..models import Marker
    rows = (
        await db.execute(select(Marker).where(Marker.media_id == id).order_by(Marker.time))
    ).scalars().all()
    return [MarkerOut.model_validate(m) for m in rows]


@router.post("/{id}/markers", response_model=MarkerOut, status_code=201)
async def create_marker(id: str, body: MarkerInput, db: AsyncSession = Depends(get_db)):
    from ..models import Marker
    asset = await db.get(MediaAsset, id)
    if not asset:
        raise HTTPException(404, "Media not found")
    if body.kind not in ("select", "reject", "marker"):
        raise HTTPException(422, "kind must be select, reject, or marker")
    m = Marker(
        media_id=id,
        time=max(0.0, body.time),
        end_time=body.end_time,
        kind=body.kind,
        note=(body.note or None),
        source="editor",
    )
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return MarkerOut.model_validate(m)


@router.delete("/{id}/markers/{marker_id}", status_code=204)
async def delete_marker(id: str, marker_id: str, db: AsyncSession = Depends(get_db)):
    from ..models import Marker
    m = await db.get(Marker, marker_id)
    if not m or m.media_id != id:
        raise HTTPException(404, "Marker not found")
    await db.delete(m)
    await db.commit()


@router.get("", response_model=MediaListResponse)
async def list_media(
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
    person: Optional[str] = Query(None),
    topic: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    sort_map = {
        "created_desc": desc(MediaAsset.created_at),
        "created_asc": MediaAsset.created_at.asc(),
        "name_asc": func.lower(MediaAsset.filename).asc(),
        "name_desc": func.lower(MediaAsset.filename).desc(),
        "duration_desc": desc(MediaAsset.duration_seconds).nulls_last(),
        "duration_asc": MediaAsset.duration_seconds.asc().nulls_last(),
        "size_desc": desc(MediaAsset.file_size_bytes).nulls_last(),
        "size_asc": MediaAsset.file_size_bytes.asc().nulls_last(),
    }
    q = select(MediaAsset).order_by(sort_map.get(sort or "", desc(MediaAsset.created_at)))
    if status:
        q = q.where(MediaAsset.status == status)
    if person:
        q = q.where(
            MediaAsset.id.in_(
                select(PersonAppearance.media_id).where(PersonAppearance.person_id == person)
            )
        )
    if topic and topic.strip():
        from ..topic_norm import normalize_topic_key

        # Compare against the same normalization the insights endpoint uses so
        # "Local AI Infrastructure" and "local_ai_infrastructure" both match.
        q = q.where(
            text(
                "EXISTS (SELECT 1 FROM jsonb_array_elements_text(media_assets.topics) AS t(v) "
                "WHERE trim(regexp_replace(regexp_replace(lower(t.v), '[_-]+', ' ', 'g'), "
                "'\\s+', ' ', 'g')) = :topic_key)"
            ).bindparams(topic_key=normalize_topic_key(topic))
        )
    if search and search.strip():
        needle = f"%{search.strip()}%"
        # Match filename only; media_assets has no title column, and matching
        # the full original_path makes every asset match when the media folder
        # name contains the search term.
        cond = MediaAsset.filename.ilike(needle)
        if "/" in search:
            # Explicit path search (query contains a slash).
            cond = cond | MediaAsset.original_path.ilike(needle)
        q = q.where(cond)

    count_q = select(func.count()).select_from(q.subquery())
    total_r = await db.execute(count_q)
    total = total_r.scalar() or 0

    q = q.offset(offset).limit(limit)
    result = await db.execute(q)
    items = result.scalars().all()

    return MediaListResponse(
        items=[MediaAssetOut.model_validate(a) for a in items],
        total=total,
    )


@router.post("", response_model=MediaAssetOut, status_code=202)
async def ingest_media(body: MediaIngestInput, db: AsyncSession = Depends(get_db)):
    if not os.path.exists(body.file_path):
        raise HTTPException(status_code=400, detail=f"File not found: {body.file_path}")

    # Dedupe by source path: the watcher rescans all roots on startup, so the
    # same file will be posted repeatedly — return the existing asset instead
    # of ingesting a duplicate.
    existing = (await db.execute(
        select(MediaAsset).where(MediaAsset.original_path == body.file_path).limit(1)
    )).scalar_one_or_none()
    if existing:
        return MediaAssetOut.model_validate(existing)

    asset = MediaAsset(
        id=str(uuid.uuid4()),
        filename=body.title or os.path.basename(body.file_path),
        original_path=body.file_path,
        status="pending",
        file_size_bytes=os.path.getsize(body.file_path),
        created_at=datetime.utcnow(),
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)

    from ..worker_client import enqueue_ingest
    await enqueue_ingest(asset.id)

    return MediaAssetOut.model_validate(asset)


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".mxf", ".ts", ".m2ts", ".wmv", ".flv", ".webm"}


@router.post("/upload", response_model=MediaAssetOut, status_code=202)
async def upload_media(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    original_name = os.path.basename(file.filename or "")
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in VIDEO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext or 'unknown'}. Supported: {', '.join(sorted(VIDEO_EXTENSIONS))}",
        )

    os.makedirs(settings.upload_dir, exist_ok=True)
    asset_id = str(uuid.uuid4())
    dest_path = os.path.join(settings.upload_dir, f"{asset_id}_{original_name}")

    from fastapi.concurrency import run_in_threadpool

    total_bytes = 0
    try:
        with open(dest_path, "wb") as out:
            while True:
                chunk = await file.read(8 * 1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds the maximum upload size of {settings.max_upload_bytes} bytes",
                    )
                # Write off the event loop so multi-GB uploads don't starve the API.
                await run_in_threadpool(out.write, chunk)
    except HTTPException:
        try:
            if os.path.exists(dest_path):
                os.remove(dest_path)
        except OSError:
            pass
        raise
    except Exception:
        try:
            if os.path.exists(dest_path):
                os.remove(dest_path)
        except OSError:
            pass
        raise HTTPException(status_code=500, detail="Failed to save uploaded file")
    finally:
        await file.close()

    if os.path.getsize(dest_path) == 0:
        os.remove(dest_path)
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    asset = MediaAsset(
        id=asset_id,
        filename=title or original_name,
        original_path=dest_path,
        status="pending",
        file_size_bytes=os.path.getsize(dest_path),
        created_at=datetime.utcnow(),
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)

    from ..worker_client import enqueue_ingest
    await enqueue_ingest(asset.id)

    return MediaAssetOut.model_validate(asset)


@router.get("/{id}", response_model=MediaAssetOut)
async def get_media(id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MediaAsset).where(MediaAsset.id == id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Media not found")
    return MediaAssetOut.model_validate(asset)


@router.delete("/{id}", status_code=204)
async def delete_media(id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MediaAsset).where(MediaAsset.id == id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Media not found")
    original_path = asset.original_path
    # Explicit cleanup in case the markers table predates the CASCADE FK.
    from ..models import Marker
    await db.execute(delete(Marker).where(Marker.media_id == id))
    await db.delete(asset)
    await db.commit()

    # Uploaded files live in our writable upload dir (unlike watched media,
    # which is mounted read-only and never touched) — clean them up.
    if original_path:
        upload_root = os.path.realpath(settings.upload_dir)
        real_path = os.path.realpath(original_path)
        if real_path.startswith(upload_root + os.sep) and os.path.isfile(real_path):
            try:
                os.remove(real_path)
            except OSError:
                import logging
                logging.getLogger("obtv.media").exception(
                    "Failed to delete uploaded file for media %s: %s", id, real_path
                )

    # Remove search vectors so deleted media stops surfacing in results.
    # Best-effort: DB row is already gone; log but don't fail if Qdrant is down.
    from ..services.qdrant_client import delete_by_media_id
    for collection in ("transcripts", "scenes"):
        try:
            await delete_by_media_id(collection, id)
        except Exception:
            import logging
            logging.getLogger("obtv.media").exception(
                "Failed to delete vectors for media %s from collection %s", id, collection
            )


@router.get("/{id}/scenes", response_model=list[SceneOut])
async def get_media_scenes(id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Scene).where(Scene.media_id == id).order_by(Scene.start_time)
    )
    return [SceneOut.model_validate(s) for s in result.scalars().all()]


@router.get("/{id}/transcript", response_model=list[TranscriptSegmentOut])
async def get_media_transcript(id: str, lang: str | None = None, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(TranscriptSegment)
        .where(TranscriptSegment.media_id == id)
        .order_by(TranscriptSegment.start_time)
    )
    segments = result.scalars().all()

    # Resolve diarization labels (SPEAKER_00, ...) to current person names so
    # transcripts reflect renames immediately.
    name_rows = await db.execute(
        select(PersonAppearance.speaker_label, Person.display_name)
        .join(Person, Person.id == PersonAppearance.person_id)
        .where(
            PersonAppearance.media_id == id,
            PersonAppearance.speaker_label.is_not(None),
        )
    )
    speaker_names = {label: name for label, name in name_rows.all() if label}

    out = []
    for s in segments:
        seg = TranscriptSegmentOut.model_validate(s)
        if lang and s.translations and s.translations.get(lang):
            seg.text = s.translations[lang]
        if seg.speaker and seg.speaker in speaker_names:
            seg.speaker = speaker_names[seg.speaker]
        out.append(seg)
    return out


@router.get("/{id}/faces", response_model=list[FaceClusterOut])
async def get_media_faces(id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(FaceCluster).where(FaceCluster.media_id == id)
    )
    clusters = result.scalars().all()
    out = []
    for c in clusters:
        appearances = [FaceAppearance(**a) for a in (c.appearances or [])]
        out.append(FaceClusterOut(
            cluster_id=c.cluster_id,
            media_id=c.media_id,
            label=c.label,
            thumbnail_url=c.thumbnail_url,
            appearances=appearances,
        ))
    return out


@router.get("/{id}/people", response_model=list[AssetPersonOut])
async def get_asset_people(id: str, db: AsyncSession = Depends(get_db)):
    """People who appear in this asset with timecoded speaking and on-camera ranges."""
    pa_rows = (
        await db.execute(
            select(PersonAppearance, Person)
            .join(Person, Person.id == PersonAppearance.person_id)
            .where(PersonAppearance.media_id == id)
        )
    ).all()
    if not pa_rows:
        return []

    segs = (
        await db.execute(
            select(TranscriptSegment)
            .where(TranscriptSegment.media_id == id, TranscriptSegment.speaker.isnot(None))
            .order_by(TranscriptSegment.start_time)
        )
    ).scalars().all()
    segs_by_speaker: dict[str, list] = {}
    for s in segs:
        segs_by_speaker.setdefault(s.speaker, []).append(s)

    clusters = (
        await db.execute(select(FaceCluster).where(FaceCluster.media_id == id))
    ).scalars().all()
    clusters_by_id = {c.cluster_id: c for c in clusters}

    grouped: dict[str, dict] = {}
    for pa, person in pa_rows:
        g = grouped.setdefault(pa.person_id, {"person": person, "appearances": []})
        g["appearances"].append(pa)

    out: list[AssetPersonOut] = []
    for person_id, g in grouped.items():
        person = g["person"]
        apps = g["appearances"]
        speakers = {pa.speaker_label for pa in apps if pa.speaker_label}
        cluster_ids = {pa.face_cluster_id for pa in apps if pa.face_cluster_id}

        speaking = [
            SpeakingMomentOut(start_time=s.start_time, end_time=s.end_time, text=s.text)
            for sp in sorted(speakers)
            for s in segs_by_speaker.get(sp, [])
        ]
        speaking.sort(key=lambda m: m.start_time)

        ranges = []
        thumbnail = None
        for cid in cluster_ids:
            c = clusters_by_id.get(cid)
            if not c:
                continue
            if thumbnail is None and c.thumbnail_url:
                thumbnail = c.thumbnail_url
            for a in c.appearances or []:
                try:
                    ranges.append((float(a["start_time"]), float(a["end_time"])))
                except (KeyError, TypeError, ValueError):
                    continue
        on_camera: list[OnCameraRangeOut] = []
        for start, end in sorted(ranges):
            if on_camera and start <= on_camera[-1].end_time:
                on_camera[-1].end_time = max(on_camera[-1].end_time, end)
            else:
                on_camera.append(OnCameraRangeOut(start_time=start, end_time=end))

        out.append(AssetPersonOut(
            person_id=person_id,
            display_name=person.display_name,
            thumbnail_url=thumbnail or person.thumbnail_url,
            speaker_label=next(iter(sorted(speakers)), None),
            speaking_seconds=sum(pa.speaking_seconds or 0 for pa in apps) or None,
            speaking=speaking,
            on_camera=on_camera,
        ))

    out.sort(key=lambda p: p.speaking_seconds or 0, reverse=True)
    return out


@router.get("/{id}/stream")
async def stream_media(id: str, db: AsyncSession = Depends(get_db)):
    from fastapi.responses import FileResponse
    result = await db.execute(select(MediaAsset).where(MediaAsset.id == id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Media not found")
    proxy = asset.proxy_path or asset.original_path
    if not proxy or not os.path.exists(proxy):
        raise HTTPException(status_code=404, detail="No streamable file available")
    return FileResponse(proxy, media_type="video/mp4")


@router.get("/{id}/frame")
async def get_media_frame(id: str, t: float = 0.0, db: AsyncSession = Depends(get_db)):
    import asyncio
    import subprocess
    from fastapi.responses import FileResponse
    result = await db.execute(select(MediaAsset).where(MediaAsset.id == id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Media not found")
    src = asset.proxy_path or asset.original_path
    if not src or not os.path.exists(src):
        raise HTTPException(status_code=404, detail="No source file available")
    t = max(0.0, t)
    if asset.duration_seconds and t >= float(asset.duration_seconds):
        t = max(0.0, float(asset.duration_seconds) - 0.5)
    frames_dir = os.path.join(settings.thumbnails_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    out_path = os.path.join(frames_dir, f"{asset.id}_{t:.1f}.jpg")
    if not os.path.exists(out_path):
        tmp_path = f"{out_path}.{uuid.uuid4().hex[:8]}.tmp.jpg"
        cmd = [
            "ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", src,
            "-frames:v", "1", "-vf", "scale=320:-2", "-q:v", "4",
            "-f", "image2", tmp_path,
        ]
        try:
            proc = await asyncio.to_thread(
                subprocess.run, cmd, capture_output=True, timeout=30
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=404, detail="Frame extraction timed out")
        if proc.returncode != 0 or not os.path.exists(tmp_path):
            raise HTTPException(status_code=404, detail="Could not extract frame")
        os.replace(tmp_path, out_path)
    return FileResponse(
        out_path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.post("/{id}/highlight", response_model=ProcessingJobOut, status_code=202)
async def create_highlight(id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MediaAsset).where(MediaAsset.id == id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Media not found")
    if not asset.key_moments:
        raise HTTPException(
            status_code=400,
            detail="No key moments available — run AI analysis first",
        )

    existing = (
        await db.execute(
            select(ProcessingJob).where(
                ProcessingJob.media_id == id,
                ProcessingJob.job_type == "highlight",
                ProcessingJob.status.in_(("pending", "running")),
            )
        )
    ).scalars().first()
    if existing:
        out = ProcessingJobOut.model_validate(existing)
        out.filename = asset.filename
        return out

    from .jobs import prune_finished_jobs
    await prune_finished_jobs(db, id, "highlight")
    job = ProcessingJob(media_id=id, job_type="highlight", status="pending", logs=[])
    db.add(job)
    await db.commit()
    await db.refresh(job)

    from ..worker_client import enqueue_job
    await enqueue_job("highlight", id, job.id)

    out = ProcessingJobOut.model_validate(job)
    out.filename = asset.filename
    return out


@router.post("/{id}/creative", response_model=ProcessingJobOut, status_code=202)
async def create_creative_pass(id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MediaAsset).where(MediaAsset.id == id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Media not found")

    has_transcript = (
        await db.execute(
            select(func.count(TranscriptSegment.id)).where(TranscriptSegment.media_id == id)
        )
    ).scalar_one()
    if not has_transcript:
        raise HTTPException(
            status_code=400,
            detail="No transcript available — the creative pass needs a transcribed asset",
        )

    existing = (
        await db.execute(
            select(ProcessingJob).where(
                ProcessingJob.media_id == id,
                ProcessingJob.job_type == "creative",
                ProcessingJob.status.in_(("pending", "running")),
            )
        )
    ).scalars().first()
    if existing:
        out = ProcessingJobOut.model_validate(existing)
        out.filename = asset.filename
        return out

    from .jobs import prune_finished_jobs
    await prune_finished_jobs(db, id, "creative")
    job = ProcessingJob(media_id=id, job_type="creative", status="pending", logs=[])
    db.add(job)
    await db.commit()
    await db.refresh(job)

    from ..worker_client import enqueue_job
    await enqueue_job("creative", id, job.id)

    out = ProcessingJobOut.model_validate(job)
    out.filename = asset.filename
    return out


def _caption_ts(seconds: float, vtt: bool) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    sep = "." if vtt else ","
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


@router.get("/{id}/captions", response_model=ClipExportResult)
async def get_captions(
    id: str, format: str = Query(...), lang: str | None = None, db: AsyncSession = Depends(get_db)
):
    fmt = format.lower()
    if fmt not in ("srt", "vtt"):
        raise HTTPException(status_code=400, detail="Format must be srt or vtt")

    asset = (await db.execute(select(MediaAsset).where(MediaAsset.id == id))).scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Media not found")

    segments = (await db.execute(
        select(TranscriptSegment)
        .where(TranscriptSegment.media_id == id)
        .order_by(TranscriptSegment.start_time)
    )).scalars().all()
    if not segments:
        raise HTTPException(status_code=404, detail="No transcript available")

    vtt = fmt == "vtt"
    lines: list[str] = ["WEBVTT", ""] if vtt else []
    for i, s in enumerate(segments, 1):
        text = s.text
        if lang and s.translations and s.translations.get(lang):
            text = s.translations[lang]
        if not vtt:
            lines.append(str(i))
        lines.append(f"{_caption_ts(s.start_time, vtt)} --> {_caption_ts(s.end_time, vtt)}")
        lines.append(f"{s.speaker}: {text}" if s.speaker else text)
        lines.append("")

    stem = os.path.splitext(asset.filename)[0]
    suffix = f".{lang}" if lang else ""
    return ClipExportResult(
        format=fmt, content="\n".join(lines), filename=f"{stem}{suffix}.{fmt}"
    )


_FILLER_TOKENS = {
    "um", "uh", "uhm", "erm", "er", "hmm", "hm", "mhm", "mm", "ah", "eh",
    "you know", "i mean", "like", "so", "well", "right", "okay", "ok", "yeah",
}


def _is_filler(text: str) -> bool:
    """True when a segment carries no content beyond filler words."""
    import re as _re
    words = [w for w in _re.sub(r"[^a-z' ]", " ", text.lower()).split() if w]
    if not words or len(words) > 4:
        return False
    return all(w in _FILLER_TOKENS for w in words)


@router.post("/{id}/tighten", response_model=TightenResult, status_code=201)
async def tighten_media(
    id: str, body: TightenInput | None = None, db: AsyncSession = Depends(get_db)
):
    body = body or TightenInput()
    threshold = max(0.3, float(body.silence_threshold))

    asset = (await db.execute(select(MediaAsset).where(MediaAsset.id == id))).scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Media not found")

    segments = (await db.execute(
        select(TranscriptSegment)
        .where(TranscriptSegment.media_id == id)
        .order_by(TranscriptSegment.start_time)
    )).scalars().all()
    if not segments:
        raise HTTPException(status_code=404, detail="No transcript available")

    duration = float(asset.duration_seconds or segments[-1].end_time)
    cuts: list[TightenCut] = []
    kept: list[tuple[float, float]] = []  # merged keep windows
    cursor = 0.0

    for s in segments:
        start, end = float(s.start_time), float(s.end_time)
        if start - cursor >= threshold:
            cuts.append(TightenCut(start=cursor, end=start, reason="silence"))
        if body.remove_fillers and _is_filler(s.text or ""):
            cuts.append(TightenCut(start=start, end=end, reason="filler"))
            cursor = max(cursor, end)
            continue
        # Keep this segment: extend the previous keep window when contiguous.
        pad_start = max(cursor, start - 0.15)
        pad_end = min(duration, end + 0.15)
        if kept and pad_start - kept[-1][1] < threshold:
            kept[-1] = (kept[-1][0], pad_end)
        else:
            kept.append((pad_start, pad_end))
        cursor = max(cursor, end)

    if duration - cursor >= threshold:
        cuts.append(TightenCut(start=cursor, end=duration, reason="silence"))

    if not kept:
        raise HTTPException(status_code=400, detail="Nothing left after tightening")

    removed = sum(c.end - c.start for c in cuts)
    stem = os.path.splitext(asset.filename)[0]
    clip_list = ClipList(
        name=f"{stem} — tightened",
        description=(
            f"Auto-tightened cut: {len(cuts)} cuts, {removed:.1f}s removed "
            f"(silence ≥ {threshold:.2f}s{', fillers' if body.remove_fillers else ''})"
        ),
    )
    db.add(clip_list)
    await db.flush()
    for pos, (ks, ke) in enumerate(kept):
        db.add(Clip(
            clip_list_id=clip_list.id, media_id=id,
            start_time=round(ks, 2), end_time=round(ke, 2),
            label=f"Keep {pos + 1:02d}", position=pos,
        ))
    await db.commit()

    return TightenResult(
        media_id=id,
        clip_list_id=clip_list.id,
        kept_segments=len(kept),
        cuts=cuts,
        removed_seconds=round(removed, 2),
        original_duration=round(duration, 2),
    )


@router.post("/{id}/roughcut", response_model=ReelJobOut, status_code=202)
async def create_rough_cut(
    id: str, body: RoughCutInput | None = None, db: AsyncSession = Depends(get_db)
):
    body = body or RoughCutInput()
    if body.preset not in ("original", "vertical"):
        raise HTTPException(status_code=400, detail="Preset must be original or vertical")

    asset = (await db.execute(select(MediaAsset).where(MediaAsset.id == id))).scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Media not found")

    suggestions = ((asset.creative or {}).get("clip_suggestions") or [])
    if not suggestions:
        raise HTTPException(
            status_code=409,
            detail="No creative clip suggestions yet — run the creative pass first",
        )

    clips = [
        {
            "media_id": id,
            "filename": asset.filename,
            "start_time": float(c["start"]),
            "end_time": float(c["end"]),
            "snippet": c.get("title") or c.get("quote"),
        }
        for c in sorted(suggestions, key=lambda c: float(c.get("start", 0)))
        if c.get("start") is not None and c.get("end") is not None
    ]
    if not clips:
        raise HTTPException(status_code=409, detail="Creative suggestions have no usable clips")

    reel = ReelJob(
        prompt=f"Rough cut — {asset.filename}",
        media_id=id,
        preset=body.preset,
        burn_captions=body.burn_captions,
        clips=clips,
        status="pending",
    )
    db.add(reel)
    await db.commit()
    await db.refresh(reel)

    from ..worker_client import enqueue_reel
    await enqueue_reel(reel.id)

    from .reels import _to_out
    return _to_out(reel)


@router.post("/{id}/social", response_model=ProcessingJobOut, status_code=202)
async def create_social_analysis(id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MediaAsset).where(MediaAsset.id == id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Media not found")

    has_transcript = (
        await db.execute(
            select(func.count(TranscriptSegment.id)).where(TranscriptSegment.media_id == id)
        )
    ).scalar_one() > 0
    if not has_transcript and not asset.synopsis:
        raise HTTPException(
            status_code=400,
            detail="No transcript or analysis available — process the media first",
        )

    existing = (
        await db.execute(
            select(ProcessingJob).where(
                ProcessingJob.media_id == id,
                ProcessingJob.job_type == "social",
                ProcessingJob.status.in_(("pending", "running")),
            )
        )
    ).scalars().first()
    if existing:
        out = ProcessingJobOut.model_validate(existing)
        out.filename = asset.filename
        return out

    from .jobs import prune_finished_jobs
    await prune_finished_jobs(db, id, "social")
    job = ProcessingJob(media_id=id, job_type="social", status="pending", logs=[])
    db.add(job)
    await db.commit()
    await db.refresh(job)

    from ..worker_client import enqueue_job
    await enqueue_job("social", id, job.id)

    out = ProcessingJobOut.model_validate(job)
    out.filename = asset.filename
    return out


# Platform → (preset, burn_captions, cut seconds). Vertical platforms get
# captions burned in because most viewers watch muted.
_SOCIAL_CUT_SPECS = {
    "youtube": ("original", False, 60.0),
    "facebook": ("original", False, 60.0),
    "x": ("original", True, 40.0),
    "instagram": ("vertical", True, 45.0),
    "tiktok": ("vertical", True, 30.0),
}
_CUTS_PER_PLATFORM = 3


@router.post("/{id}/social/cuts", response_model=list[RenderJobOut], status_code=202)
async def create_social_cuts(
    id: str, body: SocialCutsRequestIn, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(MediaAsset).where(MediaAsset.id == id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Media not found")
    if not asset.key_moments:
        raise HTTPException(
            status_code=400,
            detail="No key moments available — run AI analysis first",
        )

    if body.platform is not None:
        if body.platform not in _SOCIAL_CUT_SPECS:
            raise HTTPException(status_code=400, detail=f"Unknown platform: {body.platform}")
        platforms = [body.platform]
    else:
        scored = [
            s.get("platform") for s in (asset.social_scores or [])
            if isinstance(s, dict) and s.get("platform") in _SOCIAL_CUT_SPECS
        ]
        platforms = scored or list(_SOCIAL_CUT_SPECS)

    duration = float(asset.duration_seconds or 0)
    moments = []
    for m in asset.key_moments:
        if not isinstance(m, dict):
            continue
        try:
            t = float(m.get("time"))
        except (TypeError, ValueError):
            continue
        if t < 0 or (duration > 0 and t >= duration):
            continue
        moments.append((t, str(m.get("title") or "Key moment")))
    if not moments:
        raise HTTPException(status_code=400, detail="Key moments did not yield any usable cuts")
    moments = moments[:_CUTS_PER_PLATFORM]

    from .renders import _create_render, _mark_enqueue_failed, _to_out
    from ..worker_client import enqueue_render

    created = []
    for platform in platforms:
        preset, burn_captions, cut_seconds = _SOCIAL_CUT_SPECS[platform]
        for t, title in moments:
            start = max(0.0, t - 1.0)
            end = start + cut_seconds
            if duration > 0:
                end = min(end, duration)
            if end - start < 3.0:
                continue
            r = await _create_render(
                db, id, start, end, preset, burn_captions,
                label=f"{platform}: {title}"[:200],
            )
            created.append(r)
    if not created:
        raise HTTPException(status_code=400, detail="No usable cut windows for this asset")
    await db.commit()

    outs = []
    for r in created:
        try:
            await enqueue_render(r.id)
        except Exception as exc:
            await _mark_enqueue_failed(db, r, exc)
        outs.append(_to_out(r, asset.filename))
    return outs


SUPPORTED_TRANSLATION_LANGUAGES = {
    "es", "fr", "de", "pt", "it", "nl", "ru", "ja", "ko", "zh", "ar", "hi",
}


@router.post("/{id}/translate", response_model=ProcessingJobOut, status_code=202)
async def create_translation(id: str, body: TranslateRequest, db: AsyncSession = Depends(get_db)):
    target = body.target_language.strip().lower()
    if target not in SUPPORTED_TRANSLATION_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported language '{target}'. Supported: {', '.join(sorted(SUPPORTED_TRANSLATION_LANGUAGES))}",
        )

    result = await db.execute(select(MediaAsset).where(MediaAsset.id == id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Media not found")

    has_transcript = (
        await db.execute(
            select(func.count(TranscriptSegment.id)).where(TranscriptSegment.media_id == id)
        )
    ).scalar_one() > 0
    if not has_transcript:
        raise HTTPException(status_code=400, detail="No transcript available — process the media first")

    marker = f"Target language: {target}"
    active = (
        await db.execute(
            select(ProcessingJob).where(
                ProcessingJob.media_id == id,
                ProcessingJob.job_type == "translate",
                ProcessingJob.status.in_(("pending", "running")),
            )
        )
    ).scalars().all()
    existing = next((j for j in active if marker in (j.logs or [])), None)
    if existing:
        if existing.status == "pending":
            # Stuck "pending" usually means the queue message was lost
            # (worker restart/rebuild). Re-enqueue; the task is idempotent.
            from ..worker_client import enqueue_job
            await enqueue_job("translate", id, existing.id, extra={"target_language": target})
        out = ProcessingJobOut.model_validate(existing)
        out.filename = asset.filename
        return out

    from .jobs import prune_finished_jobs
    await prune_finished_jobs(db, id, "translate")
    job = ProcessingJob(
        media_id=id, job_type="translate", status="pending",
        logs=[f"Target language: {target}"],
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    from ..worker_client import enqueue_job
    await enqueue_job("translate", id, job.id, extra={"target_language": target})

    out = ProcessingJobOut.model_validate(job)
    out.filename = asset.filename
    return out


# Languages with a facebook/mms-tts-* model (Italian, Japanese, Chinese have none).
SUPPORTED_DUB_LANGUAGES = {
    "es", "fr", "de", "pt", "nl", "ru", "ko", "ar", "hi",
}


@router.post("/{id}/dub", response_model=ProcessingJobOut, status_code=202)
async def create_dub(id: str, body: DubRequest, db: AsyncSession = Depends(get_db)):
    target = body.target_language.strip().lower()
    if target not in SUPPORTED_DUB_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Dubbing not supported for '{target}'. Supported: {', '.join(sorted(SUPPORTED_DUB_LANGUAGES))}",
        )

    result = await db.execute(select(MediaAsset).where(MediaAsset.id == id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Media not found")

    if target not in (asset.translated_languages or []):
        raise HTTPException(
            status_code=400,
            detail=f"Transcript not translated to '{target}' yet — run translation first",
        )

    marker = f"Target language: {target}"
    active = (
        await db.execute(
            select(ProcessingJob).where(
                ProcessingJob.media_id == id,
                ProcessingJob.job_type == "dub",
                ProcessingJob.status.in_(("pending", "running")),
            )
        )
    ).scalars().all()
    existing = next((j for j in active if marker in (j.logs or [])), None)
    if existing:
        if existing.status == "pending":
            # Stuck "pending" usually means the queue message was lost
            # (worker restart/rebuild). Re-enqueue; the task is idempotent.
            from ..worker_client import enqueue_job
            await enqueue_job(
                "dub", id, existing.id,
                extra={"target_language": target, "use_cloned_voices": bool(body.use_cloned_voices)},
            )
        out = ProcessingJobOut.model_validate(existing)
        out.filename = asset.filename
        return out

    from .jobs import prune_finished_jobs
    await prune_finished_jobs(db, id, "dub")
    job = ProcessingJob(
        media_id=id, job_type="dub", status="pending",
        logs=[f"Target language: {target}"],
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    from ..worker_client import enqueue_job
    await enqueue_job("dub", id, job.id, extra={"target_language": target, "use_cloned_voices": bool(body.use_cloned_voices)})

    out = ProcessingJobOut.model_validate(job)
    out.filename = asset.filename
    return out


@router.get("/{id}/dub/{lang}/stream")
async def stream_dub(id: str, lang: str, db: AsyncSession = Depends(get_db)):
    from fastapi.responses import FileResponse
    result = await db.execute(select(MediaAsset).where(MediaAsset.id == id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Media not found")
    lang = lang.strip().lower()
    if lang not in (asset.dubbed_languages or []):
        raise HTTPException(status_code=404, detail="No dubbed audio for this language")
    path = os.path.join(settings.artifacts_root, "dubs", f"{id}_{lang}.m4a")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Dubbed audio file missing")
    return FileResponse(
        path,
        media_type="audio/mp4",
        filename=f"dub_{lang}_{asset.filename.rsplit('.', 1)[0]}.m4a",
        content_disposition_type="inline",
    )


@router.get("/{id}/dub/{lang}/video")
async def stream_dub_video(id: str, lang: str, db: AsyncSession = Depends(get_db)):
    """Dubbed video (source video stream + dubbed audio track muxed)."""
    from fastapi.responses import FileResponse
    result = await db.execute(select(MediaAsset).where(MediaAsset.id == id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Media not found")
    lang = lang.strip().lower()
    if lang not in (asset.dubbed_languages or []):
        raise HTTPException(status_code=404, detail="No dub for this language")
    path = os.path.join(settings.artifacts_root, "dubs", f"{id}_{lang}.mp4")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Dubbed video file missing — re-run dubbing to generate it")
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=f"dub_{lang}_{asset.filename.rsplit('.', 1)[0]}.mp4",
        content_disposition_type="inline",
    )


@router.get("/{id}/highlight/stream")
async def stream_highlight(id: str, db: AsyncSession = Depends(get_db)):
    from fastapi.responses import FileResponse
    result = await db.execute(select(MediaAsset).where(MediaAsset.id == id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Media not found")
    if not asset.highlight_url:
        raise HTTPException(status_code=404, detail="No highlight reel available")
    path = os.path.join(settings.artifacts_root, "reels", asset.highlight_url)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Highlight reel file missing")
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=f"highlight_{asset.filename.rsplit('.', 1)[0]}.mp4",
        content_disposition_type="inline",
    )
