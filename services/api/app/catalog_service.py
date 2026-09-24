"""Durable checkpoints and bounded admission; all side effects explicitly opted in."""
import os
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import select, func, text
from starlette.requests import Request

from .catalog import ASSET_TYPES, INITIAL_CURSOR, CatalogClient, eligibility, exact_id, next_cursor
from .catalog_models import CatalogAsset, CatalogCheckpoint, CatalogRun
from .commands.import_curator_workbook import ImportFailure, _field_values
from .database import AsyncSessionLocal, engine
from .models import MediaAsset, ProcessingJob


class CatalogOptions(BaseModel):
    dry_run: bool = True
    max_pages: int = Field(default=1, ge=1, le=100)
    max_assets: int = Field(default=10, ge=1, le=100)
    max_inflight: int = Field(default=10, ge=1, le=100)
    storage_paths: list[str] = Field(default_factory=list, max_length=20)
    min_free_bytes: int = Field(default=20 * 1024**3, ge=1024**3)
    reserve_per_asset_bytes: int = Field(default=1024**3, ge=1024**2)
    max_attempts: int = Field(default=3, ge=1, le=10)
    confirm: str = ""


def field(asset, name):
    values = list(dict.fromkeys(_field_values(asset, (name,))))
    if len(values) > 1:
        raise ImportFailure(f"Ambiguous {name}")
    return values[0] if values else None


def storage_available(options, admitted):
    if not options.storage_paths:
        raise ImportFailure("Apply requires explicit storage_paths for all analysis/scratch volumes")
    for root in options.storage_paths:
        if not os.path.isabs(root) or not os.path.isdir(root):
            raise ImportFailure("Storage watermark path is not an available absolute directory")
        if shutil.disk_usage(root).free < options.min_free_bytes + (admitted + 1) * options.reserve_per_asset_bytes:
            return False
    return True


def exact_nonvideo_source(value: str, asset_type: str | None = None) -> str:
    """Resolve exact files or verified single-render directory references."""
    root = Path(os.environ.get("CURATOR_PROXY_ROOT", "/curator")).resolve()
    raw = (value or "").replace("\\", "/")
    parts = [p for p in raw.split("/") if p]
    if ".." in parts:
        raise ImportFailure("Parent segment in WebProxyPath")
    if raw.startswith(str(root) + "/"):
        path = Path(raw).resolve()
    else:
        markers = [i for i, part in enumerate(parts) if part.casefold() == "webproxy"]
        if not markers:
            raise ImportFailure("Non-video WebProxyPath has no verified WebProxy mount mapping")
        path = root.joinpath(*parts[markers[-1] + 1:]).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ImportFailure("Non-video WebProxyPath escapes the Curator mount")
    if path.is_dir():
        directory = path

        def child(name):
            if not name or Path(name).name != name or "\\" in name:
                raise ImportFailure("Invalid non-video manifest reference")
            p = (directory / name).resolve()
            if p.parent != directory or not p.is_file() or not p.stat().st_size:
                raise ImportFailure("Non-video render reference is missing or escapes its directory")
            return p

        def playlist(p):
            if p.stat().st_size > 8 * 1024 * 1024:
                raise ImportFailure("Non-video manifest exceeds size limit")
            content = p.read_text(encoding="utf-8-sig")
            if not content.startswith("#EXTM3U"):
                raise ImportFailure("Invalid non-video HLS manifest")
            return content

        if asset_type == "Image":
            candidates = [p.name for p in directory.iterdir()
                          if p.stem == directory.name and p.suffix.lower() in
                          {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif"}]
            if len(candidates) != 1:
                raise ImportFailure("Image render requires exactly one same-basename image")
            path = child(candidates[0])
        elif asset_type == "Audio":
            master = playlist(child(directory.name + ".m3u8"))
            audio_lines = [line for line in master.splitlines()
                           if line.startswith("#EXT-X-MEDIA:") and
                           re.search(r"(?:[:,])TYPE=AUDIO(?:,|$)", line)]
            references = [re.findall(r'(?:[:,])URI="([^"]+)"', line) for line in audio_lines]
            if len(references) != 1 or len(references[0]) != 1:
                raise ImportFailure("Audio render requires exactly one manifest audio track")
            reference = references[0][0]
            if not re.fullmatch(re.escape(directory.name) + r"_audio\d+\.m3u8", reference):
                raise ImportFailure("Audio manifest reference does not match this render")
            track = playlist(child(reference))
            files = set(re.findall(r'URI="([^"]+)"', track))
            files.update(line.strip() for line in track.splitlines()
                         if line.strip() and not line.startswith("#"))
            expected = reference.removesuffix(".m3u8") + ".mp4"
            if files != {expected}:
                raise ImportFailure("Audio manifest must reference one matching media file")
            path = child(expected)
        else:
            raise ImportFailure("Directory WebProxyPath requires explicit Audio or Image type")
    if not path.is_file() or path.stat().st_size == 0:
        raise ImportFailure("Non-video WebProxyPath must identify one readable nonempty file under the Curator mount")
    return str(path)


async def import_asset(db, candidate):
    if candidate.dispatch_state == "pending":
        return await publish_dispatch(db, candidate)
    if candidate.media_id and candidate.dispatch_state == "failed":
        await prepare_dispatch(db, candidate)
        return await publish_dispatch(db, candidate)
    data = candidate.metadata_snapshot
    proxy = field(data, "WebProxyPath")
    if not proxy:
        raise ImportFailure("Missing WebProxyPath; no alternate source path will be guessed")
    if candidate.asset_type == "Media":
        # Reuse the durable XML import contract, including its publish retry and
        # exact Id/path linkage. No changes to the playback router are needed.
        from .routers.media import curator_manifest_import
        from .schemas import CuratorManifestImportIn, CuratorManifestAssetIn
        from .config import settings
        if not settings.internal_api_token:
            raise ImportFailure("INTERNAL_API_TOKEN is required for curator-import")
        request = Request({"type": "http", "headers": [
            (b"x-internal-token", settings.internal_api_token.encode()),
        ]})
        result = await curator_manifest_import(CuratorManifestImportIn(
            manifest_name="bounded-catalog",
            assets=[CuratorManifestAssetIn(
                asset_id=candidate.asset_id, name=field(data, "Name"),
                web_proxy_path=proxy, folder_path=field(data, "FolderPath"),
                requested_by="bounded-catalog",
            )],
        ), request, db)
        item = result.items[0]
        if item.status not in ("queued", "existing"):
            raise ImportFailure(item.error or f"Curator import {item.status}")
        candidate.job_id = item.job_id
        candidate.dispatch_state = "published"
        return item.media_id, item.status
    if candidate.asset_type not in ("Audio", "Image"):
        raise ImportFailure(f"Unsupported asset type: {candidate.asset_type}")
    source = await run_in_threadpool(exact_nonvideo_source, proxy, candidate.asset_type)
    await db.execute(text(
        "SELECT pg_advisory_xact_lock(hashtext('obtv_curator_import:' || :id))"
    ), {"id": candidate.asset_id})
    media = (await db.execute(select(MediaAsset).where(
        (MediaAsset.curator_asset_id == candidate.asset_id) | (MediaAsset.original_path == source)
    ).limit(1))).scalar_one_or_none()
    if media is not None:
        candidate.media_id = media.id
        return media.id, "existing"
    if media is None:
        media = MediaAsset(
            id=str(uuid.uuid4()), filename=field(data, "Name") or Path(source).name,
            original_path=source, curator_asset_id=candidate.asset_id,
            curator_web_proxy_path=proxy, curator_folder_path=field(data, "FolderPath"),
            curator_requested_by="bounded-catalog", status="pending",
            file_size_bytes=os.path.getsize(source),
        )
        db.add(media)
        await db.flush()
    candidate.media_id = media.id
    await prepare_dispatch(db, candidate)
    return await publish_dispatch(db, candidate)


async def prepare_dispatch(db, candidate):
    """Persist an outbox + job in one commit; never allocate again on publish retry."""
    job_id = str(uuid.uuid4())
    job_type = "ingest" if candidate.asset_type == "Media" else "catalog_ingest"
    params = {} if candidate.asset_type == "Media" else {"asset_type": candidate.asset_type}
    db.add(ProcessingJob(id=job_id, media_id=candidate.media_id, job_type=job_type,
                         status="pending", progress=0, logs=[], params=params))
    candidate.job_id = candidate.task_id = job_id
    candidate.dispatch_state = "pending"
    media = await db.get(MediaAsset, candidate.media_id)
    media.status = "pending"
    media.processing_stage = "queued_for_processing"
    await db.commit()


async def publish_dispatch(db, candidate):
    job = await db.get(ProcessingJob, candidate.job_id)
    if job is None:
        raise ImportFailure("Catalog outbox references a missing job")
    if job.status in ("running", "success"):
        candidate.dispatch_state = "published"
        await db.commit()
        return candidate.media_id, "queued"
    if job.status != "pending":
        candidate.dispatch_state = "failed"
        await db.commit()
        raise ImportFailure("Previous catalog worker attempt failed or was cancelled")
    from .worker_client import _publish
    params = {"media_id": candidate.media_id, "job_id": candidate.job_id}
    if candidate.asset_type != "Media":
        params["asset_type"] = candidate.asset_type
    await _publish(
        "gpu" if candidate.asset_type == "Image" else "ingest",
        "tasks.ingest.run_ingest_pipeline" if candidate.asset_type == "Media" else "tasks.catalog_media.ingest",
        params, candidate.task_id,
    )
    # A crash here leaves "pending": the same job/task is republished. Worker
    # per-asset locks and terminal-job checks prevent a second pipeline.
    candidate.dispatch_state = "published"
    await db.commit()
    return candidate.media_id, "queued"


async def reconcile(db, options):
    """Bounded rotating poll, not a scan of all catalog rows on every run."""
    rows = (await db.execute(select(CatalogAsset).where(
        CatalogAsset.status.in_(("queued", "existing", "retry", "failed"))
    ).order_by(CatalogAsset.updated_at, CatalogAsset.asset_id).limit(100))).scalars().all()
    for candidate in rows:
        candidate.updated_at = datetime.utcnow()
        if candidate.attempts >= options.max_attempts and candidate.status == "retry":
            candidate.status = "failed"
            continue
        if not candidate.media_id:
            continue
        media = await db.get(MediaAsset, candidate.media_id)
        if not media:
            candidate.status, candidate.error = "failed", "Linked media asset was removed"
            continue
        active = (await db.execute(select(func.count()).select_from(ProcessingJob).where(
            ProcessingJob.media_id == candidate.media_id,
            ProcessingJob.status.in_(("pending", "running")),
        ))).scalar()
        if active:
            continue
        root_job = await db.get(ProcessingJob, candidate.job_id) if candidate.job_id else None
        if root_job and root_job.status == "cancelled":
            candidate.status, candidate.dispatch_state = "failed", "failed"
            candidate.error = "Catalog ingest was cancelled; explicit retry reset required"
            continue
        errors = 0
        if root_job:
            errors = (await db.execute(select(func.count()).select_from(ProcessingJob).where(
                ProcessingJob.media_id == candidate.media_id, ProcessingJob.status == "error",
                ProcessingJob.created_at >= root_job.created_at,
            ))).scalar()
        if media.status == "error" or errors:
            candidate.status = "retry" if candidate.attempts < options.max_attempts else "failed"
            candidate.dispatch_state = "failed"
            candidate.error = "Worker processing failed; bounded retry required"
        elif media.status == "ready":
            candidate.status, candidate.error = "complete", None
    await db.commit()


async def run_catalog(options: CatalogOptions) -> dict:
    if not options.dry_run and options.confirm != "QUEUE_BOUNDED_CATALOG":
        raise ImportFailure("Apply requires confirm=QUEUE_BOUNDED_CATALOG")
    if not options.dry_run:
        from .catalog_storage import require_archive_storage
        try:
            verified_paths = await run_in_threadpool(require_archive_storage)
        except (RuntimeError, OSError) as exc:
            raise ImportFailure(_safe_error(exc)) from exc
        options.storage_paths = list(dict.fromkeys(verified_paths + options.storage_paths))
        storage_available(options, 0)
    # Dedicated connection: import helpers commit their sessions; a transaction
    # lock on that session would silently cease protecting the admission budget.
    async with engine.connect() as lock:
        locked = (await lock.execute(text(
            "SELECT pg_try_advisory_lock(hashtext('obtv_catalog_run'))"
        ))).scalar()
        await lock.commit()
        if not locked:
            raise ImportFailure("A catalog run is already active")
        try:
            async with AsyncSessionLocal() as db:
                return await _run(db, options)
        finally:
            await lock.execute(text("SELECT pg_advisory_unlock(hashtext('obtv_catalog_run'))"))
            await lock.commit()


async def _run(db, options):
    run_id = str(uuid.uuid4())
    stats = {"pages": 0, "seen": 0, "new": 0, "duplicates": 0, "review": 0,
             "admitted": 0, "errors": 0, "stop": "bounded"}
    run = CatalogRun(id=run_id, options=options.model_dump(exclude={"confirm"}), stats=dict(stats))
    db.add(run)
    checkpoint = await db.get(CatalogCheckpoint, "catalog")
    if checkpoint is None:
        checkpoint = CatalogCheckpoint(id="catalog", cursor=dict(INITIAL_CURSOR), stats={})
        db.add(checkpoint)
    await db.commit()
    client = None
    try:
        client = CatalogClient()
        for _ in range(options.max_pages):
            cursor = dict(checkpoint.cursor)
            asset_type = ASSET_TYPES[cursor["type_index"]]
            page = await run_in_threadpool(client.page, asset_type, cursor["offset"], dated=cursor["dated"])
            for asset in page:
                asset_id = exact_id(asset)  # malformed IDs stop without advancing the page
                state, error = eligibility(asset)
                row = await db.get(CatalogAsset, asset_id)
                stats["seen"] += 1
                if row is None:
                    row = CatalogAsset(asset_id=asset_id, asset_type=asset_type,
                                       metadata_snapshot=asset, status=state, error=error)
                    db.add(row)
                    stats["new"] += 1
                else:
                    stats["duplicates"] += 1
                    if row.asset_type != asset_type:
                        raise ImportFailure("Curator Id appeared under conflicting assetTypes")
                    row.metadata_snapshot = asset
                    if row.status in ("eligible", "review", "excluded"):
                        row.status, row.error = state, error
                    row.updated_at = datetime.utcnow()
                if state == "review":
                    stats["review"] += 1
                await db.flush()
            checkpoint.cursor = next_cursor(cursor, len(page))
            checkpoint.updated_at = datetime.utcnow()
            checkpoint.last_error = None
            stats["pages"] += 1
            run.stats = dict(stats)
            await db.commit()  # page rows + cursor atomically committed
        await reconcile(db, options)
        if not options.dry_run:
            candidates = (await db.execute(select(CatalogAsset).where(
                CatalogAsset.status.in_(("eligible", "retry")),
                CatalogAsset.attempts < options.max_attempts,
            ).order_by(CatalogAsset.updated_at, CatalogAsset.asset_id).limit(options.max_assets))).scalars().all()
            for candidate in candidates:
                state, error = eligibility(candidate.metadata_snapshot)
                if state != "eligible":
                    candidate.status, candidate.error = state, error
                    await db.commit()
                    continue
                if candidate.media_id is None:
                    candidate.media_id = (await db.execute(select(MediaAsset.id).where(
                        MediaAsset.curator_asset_id == candidate.asset_id
                    ).limit(1))).scalar_one_or_none()
                if candidate.asset_type == "Media" and candidate.media_id and not candidate.job_id:
                    from .models import CuratorInboxImport
                    imported = await db.get(CuratorInboxImport, candidate.asset_id)
                    if imported and imported.job_id and imported.status in ("publish_pending", "publish_failed", "failed"):
                        root = await db.get(ProcessingJob, imported.job_id)
                        if root and root.status == "pending":
                            candidate.job_id = candidate.task_id = root.id
                            candidate.dispatch_state = "pending"
                            await db.commit()
                inflight = (await db.execute(select(func.count(func.distinct(MediaAsset.id))).where(
                    (MediaAsset.status.in_(("pending", "processing"))) |
                    (MediaAsset.id.in_(select(ProcessingJob.media_id).where(
                        ProcessingJob.status.in_(("pending", "running"))
                    )))
                ))).scalar() or 0
                # A publish-failed candidate already occupies an inflight slot.
                reserved_retry = bool(candidate.media_id and (await db.execute(
                    select(MediaAsset.id).where(
                        MediaAsset.id == candidate.media_id,
                        (MediaAsset.status.in_(("pending", "processing"))) |
                        (MediaAsset.id.in_(select(ProcessingJob.media_id).where(
                            ProcessingJob.status.in_(("pending", "running"))
                        ))),
                    )
                )).scalar_one_or_none())
                if inflight >= options.max_inflight and not reserved_retry:
                    stats["stop"] = "max_inflight"
                    break
                if not storage_available(options, stats["admitted"]):
                    stats["stop"] = "storage_watermark"
                    break
                candidate.attempts += 1
                candidate.updated_at = datetime.utcnow()
                await db.commit()
                candidate_id = candidate.asset_id
                try:
                    media_id, status = await import_asset(db, candidate)
                    candidate.media_id, candidate.status, candidate.error = media_id, status, None
                    stats["admitted"] += 1
                except Exception as exc:
                    await db.rollback()
                    candidate = await db.get(CatalogAsset, candidate_id)
                    candidate.status = "retry"
                    candidate.error = _safe_error(exc)
                    if candidate.media_id is None:
                        # The XML importer may have committed its durable outbox
                        # before publishing failed. Permit retry of that reserved
                        # slot even when the inflight ceiling has been reached.
                        existing = (await db.execute(select(MediaAsset.id).where(
                            MediaAsset.curator_asset_id == candidate_id
                        ).limit(1))).scalar_one_or_none()
                        candidate.media_id = existing
                    if candidate.job_id is None and candidate.asset_type == "Media":
                        from .models import CuratorInboxImport
                        imported = await db.get(CuratorInboxImport, candidate_id)
                        if imported:
                            candidate.job_id = imported.job_id
                            root = await db.get(ProcessingJob, imported.job_id) if imported.job_id else None
                            if root and root.status == "pending":
                                candidate.task_id = root.id
                                candidate.dispatch_state = "pending"
                    if candidate.attempts >= options.max_attempts:
                        candidate.status = "failed"
                    stats["errors"] += 1
                await db.commit()
    except Exception as exc:
        await db.rollback()
        run = await db.get(CatalogRun, run_id)
        checkpoint = await db.get(CatalogCheckpoint, "catalog")
        run.error = checkpoint.last_error = _safe_error(exc)
        stats["errors"] += 1
        stats["stop"] = "error"
    finally:
        if client:
            client.close()
    # Import helpers may roll back, expiring unrelated ORM objects in this
    # session. Explicitly reload instead of triggering async lazy IO on access.
    run = await db.get(CatalogRun, run_id)
    checkpoint = await db.get(CatalogCheckpoint, "catalog")
    run.stats = dict(stats)
    run.finished_at = datetime.utcnow()
    checkpoint.stats = dict(stats)
    await db.commit()
    return {"run_id": run_id, "stats": stats, "cursor": checkpoint.cursor, "error": run.error}


def _safe_error(exc):
    # HTTP exceptions may include credential-bearing URLs; use established scrubber.
    from .commands.import_curator_workbook import _safe_error as scrub
    return scrub(exc)[:2000]