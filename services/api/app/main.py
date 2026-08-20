import os
import tempfile

# Starlette's multipart parser spools incoming uploads to a temp file BEFORE
# the endpoint handler runs. The container's /tmp lives on the Docker overlay
# filesystem, so multi-GB uploads fill the Docker root partition and kill the
# request mid-stream (browser sees ERR_CONNECTION_RESET). Spool onto the
# uploads volume instead — it is host storage sized for media.
_spool_dir = os.environ.get("UPLOAD_SPOOL_DIR", "/uploads/.tmp")
try:
    os.makedirs(_spool_dir, exist_ok=True)
    tempfile.tempdir = _spool_dir
    # Clear spool files orphaned by a previous crash/restart mid-upload.
    for _f in os.listdir(_spool_dir):
        try:
            os.remove(os.path.join(_spool_dir, _f))
        except OSError:
            pass
except OSError:
    pass  # volume not mounted (e.g. local dev) — fall back to default /tmp

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .database import engine, Base
from .config import settings
from .routers import media, search, jobs, ai, clips, people, insights, renders, reels, stories, projects, project_chat, voice, graphics, trends, ratings, folders, socials, curator, auth as auth_router, users as users_router, audit as audit_router
from .auth import auth_middleware


# Columns created as `json` by earlier versions must become `jsonb` so workers
# can append with the || operator. Idempotent: no-op once the type is jsonb.
_JSONB_MIGRATIONS = [
    ("processing_jobs", "logs"),
    ("face_clusters", "appearances"),
    ("ai_messages", "citations"),
]


# Columns added after initial release; create_all does not alter existing tables.
_COLUMN_MIGRATIONS = [
    ("voice_generations", "video_status", "VARCHAR"),
    ("voice_generations", "video_path", "VARCHAR"),
    ("voice_generations", "video_error", "TEXT"),
    ("voice_generations", "video_task_id", "VARCHAR"),
    ("people", "lipsync_reference_path", "VARCHAR"),
    ("ai_messages", "project_id", "VARCHAR"),
    ("ai_messages", "project_name", "VARCHAR"),
    ("processing_jobs", "params", "JSONB"),
    ("media_assets", "synopsis", "TEXT"),
    ("media_assets", "key_moments", "JSONB"),
    ("media_assets", "topics", "JSONB"),
    ("media_assets", "highlight_url", "TEXT"),
    ("media_assets", "social_scores", "JSONB"),
    ("media_assets", "translated_languages", "JSONB"),
    ("media_assets", "dubbed_languages", "JSONB"),
    ("transcript_segments", "translations", "JSONB"),
    ("transcript_segments", "sentiment", "DOUBLE PRECISION"),
    ("transcript_segments", "emotion", "TEXT"),
    ("media_assets", "speaker_embeddings", "JSONB"),
    ("media_assets", "sprite_url", "TEXT"),
    ("media_assets", "sprite_meta", "JSONB"),
    ("face_clusters", "embedding", "JSONB"),
    ("reel_jobs", "media_id", "TEXT"),
    ("social_channel_analyses", "top_videos", "JSONB"),
    ("social_channel_analyses", "ai_sections", "JSONB"),
    ("social_channel_analyses", "avg_views", "DOUBLE PRECISION"),
    ("social_channel_analyses", "avg_likes", "DOUBLE PRECISION"),
    ("social_channel_analyses", "avg_comments", "DOUBLE PRECISION"),
    ("social_channel_analyses", "engagement_rate", "DOUBLE PRECISION"),
    ("projects", "media_ranges", "JSONB"),
    ("reel_jobs", "cut_version", "INTEGER"),
    ("media_assets", "creative", "JSONB"),
    ("clip_lists", "project_id", "TEXT"),
    ("render_jobs", "project_id", "TEXT"),
    ("reel_jobs", "project_id", "TEXT"),
    ("story_jobs", "project_id", "TEXT"),
    ("story_jobs", "target_duration_seconds", "DOUBLE PRECISION"),
    ("processing_jobs", "heartbeat_at", "TIMESTAMP"),
    ("processing_jobs", "cleared_at", "TIMESTAMP"),
    ("media_assets", "folder_id", "TEXT"),
    ("media_folders", "parent_id", "TEXT"),
    ("projects", "status", "TEXT NOT NULL DEFAULT 'active'"),
    ("projects", "media_ids", "JSONB"),
    ("projects", "target_runtime_seconds", "DOUBLE PRECISION"),
    ("reel_jobs", "target_duration_seconds", "DOUBLE PRECISION"),
    ("reel_jobs", "pace", "TEXT"),
    ("reel_jobs", "rating", "TEXT"),
    ("reel_jobs", "candidate_clips", "JSONB"),
    ("people", "voice_preset", "TEXT"),
    ("voice_generations", "preset", "TEXT"),
    ("people", "voice_settings", "JSONB"),
    ("voice_generations", "settings", "JSONB"),
    ("render_jobs", "publish_stats", "JSONB"),
    ("media_assets", "qc_flags", "JSONB"),
    ("clip_lists", "locked", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("clips", "approved", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("clips", "match_reason", "TEXT"),
    ("library_insights", "opportunities", "JSONB"),
    ("library_insights", "coverage_gaps", "JSONB"),
    ("render_jobs", "unreviewed", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("reel_jobs", "unreviewed", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("person_appearances", "merged_from", "JSONB"),
    ("people", "face_search", "JSONB"),
    ("media_assets", "recorded_at", "TIMESTAMP"),
    ("media_assets", "source_path", "TEXT"),
    ("story_jobs", "script", "TEXT"),
    ("media_assets", "curator_asset_id", "VARCHAR"),
    ("media_assets", "curator_folder_path", "VARCHAR"),
    ("media_assets", "curator_web_proxy_path", "VARCHAR"),
    ("media_assets", "curator_requested_by", "VARCHAR"),
    ("curator_asset_records", "requested_by", "VARCHAR"),
]


# Library-wide jobs (e.g. insights) have no media asset.
_NULLABLE_MIGRATIONS = [
    ("processing_jobs", "media_id"),
]


async def _run_startup_migrations():
    from sqlalchemy import text

    async with engine.begin() as conn:
        # Busy workers hold long locks on hot tables (e.g. transcript_segments).
        # Bound how long DDL waits so a busy library can't deadlock startup;
        # the retry loop in lifespan() handles the timeout.
        await conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        await conn.run_sync(Base.metadata.create_all)

        # ALTER TABLE takes an ACCESS EXCLUSIVE lock even when the column
        # already exists (IF NOT EXISTS checks AFTER locking). On a busy
        # library the workers hold long locks on hot tables, so re-running
        # the whole migration list on every boot deadlocks startup. Read the
        # catalog first and only ALTER what is actually missing.
        existing = {
            (r[0], r[1])
            for r in (await conn.execute(text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public'"
            ))).fetchall()
        }
        for table, column, coltype in _COLUMN_MIGRATIONS:
            if (table, column) in existing:
                continue
            await conn.execute(text(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {coltype}"
            ))
        nullable = {
            (r[0], r[1])
            for r in (await conn.execute(text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND is_nullable = 'YES'"
            ))).fetchall()
        }
        for table, column in _NULLABLE_MIGRATIONS:
            if (table, column) in nullable:
                continue
            await conn.execute(text(
                f"ALTER TABLE {table} ALTER COLUMN {column} DROP NOT NULL"
            ))
        for table, column in _JSONB_MIGRATIONS:
            await conn.execute(text(
                f"""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = '{table}' AND column_name = '{column}'
                          AND data_type = 'json'
                    ) THEN
                        ALTER TABLE {table}
                        ALTER COLUMN {column} TYPE jsonb
                        USING {column}::jsonb;
                    END IF;
                END $$;
                """
            ))

        # At most one active library-wide insights job: the refresh endpoint
        # relies on this index to make its dedupe race-free.
        await conn.execute(text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_processing_jobs_active_insights
            ON processing_jobs (job_type)
            WHERE job_type = 'insights' AND status IN ('pending', 'running')
            """
        ))

        # Queue-view queries filter on cleared_at IS NULL; keep them fast as
        # soft-cleared history accumulates.
        await conn.execute(text(
            """
            CREATE INDEX IF NOT EXISTS ix_processing_jobs_active_queue
            ON processing_jobs (created_at DESC)
            WHERE cleared_at IS NULL
            """
        ))

        # Same singleton guarantee for library-wide trends refresh jobs.
        await conn.execute(text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_processing_jobs_active_trends
            ON processing_jobs (job_type)
            WHERE job_type = 'trends' AND status IN ('pending', 'running')
            """
        ))

        # Same singleton guarantee for library-wide social sync jobs.
        await conn.execute(text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_processing_jobs_active_social_sync
            ON processing_jobs (job_type)
            WHERE job_type = 'social_sync' AND status IN ('pending', 'running')
            """
        ))

        # One-time data fixup: thumbnail_url must store bare filenames; older
        # worker versions stored them with the /api/thumbnails/ prefix, which
        # the frontend prepends again (double prefix -> 404 broken images).
        for table in ("scenes", "media_assets"):
            await conn.execute(text(
                f"""
                UPDATE {table}
                SET thumbnail_url = regexp_replace(thumbnail_url, '^/api/thumbnails/', '')
                WHERE thumbnail_url LIKE '/api/thumbnails/%'
                """
            ))

    await _bootstrap_admin()


async def _bootstrap_admin():
    """Create the first admin account when the users table is empty."""
    import secrets as _secrets
    from sqlalchemy import select, func
    from .auth import hash_password
    from .database import AsyncSessionLocal
    from .models import User

    async with AsyncSessionLocal() as db:
        count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
        if count > 0:
            return
        username = (settings.admin_username or "admin").strip().lower()
        password = settings.admin_password
        generated = not password
        if generated:
            password = _secrets.token_urlsafe(12)
        db.add(User(username=username, password_hash=hash_password(password), role="admin", display_name="Admin"))
        await db.commit()
        if generated:
            print("=" * 72)
            print("  FIRST-RUN ADMIN ACCOUNT CREATED")
            print(f"  username: {username}")
            print(f"  password: {password}")
            print("  Set ADMIN_PASSWORD in .env to control this, and change the")
            print("  password after first login. This is printed ONLY once.")
            print("=" * 72)
        else:
            print(f"Bootstrap admin account created: {username} (password from ADMIN_PASSWORD)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    # DDL can lose a deadlock/lock-timeout race against busy workers; every
    # statement is idempotent, so just retry instead of failing startup.
    attempts = 5
    for attempt in range(1, attempts + 1):
        try:
            await _run_startup_migrations()
            break
        except Exception as e:
            if attempt == attempts:
                raise
            print(f"Startup migrations blocked (attempt {attempt}/{attempts}): {e}; retrying in 5s")
            await asyncio.sleep(5)

    try:
        from .services.qdrant_client import ensure_collections
        await ensure_collections()
    except Exception as e:
        print(f"Warning: Qdrant not available: {e}")

    os.makedirs(settings.proxies_dir, exist_ok=True)
    os.makedirs(settings.thumbnails_dir, exist_ok=True)
    os.makedirs(settings.audio_dir, exist_ok=True)
    os.makedirs(settings.renders_dir, exist_ok=True)

    # Warm AI models in the background so the first /ai/ask request does not
    # stall for minutes on model download + load. Non-blocking: the API serves
    # requests immediately; the first ask simply waits on the shared lazy
    # loaders if it arrives before warm-up finishes.
    import threading
    import time

    def _ts() -> str:
        return time.strftime("%H:%M:%S")

    def _warm_models():
        print(f"[{_ts()}] Warm-up: thread started")
        t0 = time.monotonic()
        try:
            from .services.embedding import _load_model
            print(f"[{_ts()}] Warm-up: loading text embedding model...")
            _load_model()
            print(f"[{_ts()}] Warm-up: text embedding model ready ({time.monotonic() - t0:.0f}s)")
        except Exception as e:
            print(f"[{_ts()}] Warm-up: embedding model failed to load: {e}")
        t1 = time.monotonic()
        try:
            from .services.llm_remote import remote_enabled
            if remote_enabled():
                print(f"[{_ts()}] Warm-up: remote LLM mode (LLM_BASE_URL set) — local LLM warm-up skipped")
            else:
                from .services.llm import _load_pipeline
                print(f"[{_ts()}] Warm-up: loading LLM (downloads shards here if cache is cold)...")
                _load_pipeline()
                print(f"[{_ts()}] Warm-up: LLM pipeline ready ({time.monotonic() - t1:.0f}s)")
        except Exception as e:
            print(f"[{_ts()}] Warm-up: LLM failed to load: {e}")

    threading.Thread(target=_warm_models, daemon=True).start()

    # Backfill recorded_at from source file mtimes for assets ingested before
    # the column existed — the keyword heatmap is meaningless without real
    # content dates on a bulk-ingested archive. One-time per asset; files that
    # are missing/unreadable are simply skipped (heatmap falls back to
    # created_at for them).
    async def _backfill_recorded_at():
        from sqlalchemy import text as sql_text
        from .database import AsyncSessionLocal
        try:
            async with AsyncSessionLocal() as db:
                rows = (await db.execute(sql_text(
                    "SELECT id, original_path FROM media_assets "
                    "WHERE recorded_at IS NULL AND original_path IS NOT NULL"
                ))).all()
                if not rows:
                    return
                print(f"[{_ts()}] recorded_at backfill: dating {len(rows)} assets from file mtimes...")
                updated = 0
                for asset_id, path in rows:
                    try:
                        mtime = await asyncio.to_thread(os.path.getmtime, path)
                    except OSError:
                        continue
                    await db.execute(
                        sql_text("UPDATE media_assets SET recorded_at = to_timestamp(:ts) AT TIME ZONE 'UTC' WHERE id = :id"),
                        {"ts": float(mtime), "id": asset_id},
                    )
                    updated += 1
                await db.commit()
                print(f"[{_ts()}] recorded_at backfill: dated {updated}/{len(rows)} assets")
        except Exception as e:
            print(f"[{_ts()}] recorded_at backfill failed: {e}")

    backfill_task = asyncio.create_task(_backfill_recorded_at())

    # Reap phantom "running" jobs: if a worker container is rebuilt/restarted
    # mid-task, the task process dies without updating its ProcessingJob row,
    # which then shows "running" forever. Periodically cross-check running
    # jobs against the Celery cluster's actual active/reserved task ids and
    # fail the ones no worker knows about.
    async def _reap_stale_jobs_loop():
        from sqlalchemy import text as sql_text
        from .database import AsyncSessionLocal
        from .worker_client import _celery

        def _live_task_ids() -> set[str] | None:
            insp = _celery.control.inspect(timeout=5.0)
            ids: set[str] = set()
            saw_worker = False
            for getter in (insp.active, insp.reserved, insp.scheduled):
                try:
                    d = getter()
                except Exception:
                    return None
                if not d:
                    continue
                saw_worker = True
                for tasks in d.values():
                    for t in tasks or []:
                        tid = t.get("id") or (t.get("request") or {}).get("id")
                        if tid:
                            ids.add(str(tid))
            return ids if saw_worker else None

        # A job is only reaped after BOTH: (a) its task id was absent from
        # inspect for 2 consecutive cycles (a single missed broadcast reply
        # from one busy worker is normal and must not kill its live jobs) and
        # (b) its heartbeat_at is >10 minutes stale (every update_job /
        # append_log from the worker bumps it). A falsely reaped job could be
        # retried into duplicate execution, so err on the side of leaving it.
        missing_counts: dict[tuple[str, str], int] = {}
        await asyncio.sleep(60)
        while True:
            try:
                live = await asyncio.to_thread(_live_task_ids)
                # No worker replied — broker down or all workers restarting.
                # Don't guess; try again next cycle.
                if live is not None:
                    async with AsyncSessionLocal() as db:
                        rows = (await db.execute(sql_text(
                            "SELECT id, celery_task_id FROM processing_jobs "
                            "WHERE status = 'running' AND celery_task_id IS NOT NULL "
                            "AND started_at < (now() AT TIME ZONE 'utc') - interval '3 minutes' "
                            "AND (heartbeat_at IS NULL OR heartbeat_at < (now() AT TIME ZONE 'utc') - interval '10 minutes')"
                        ))).all()
                        current_keys = set()
                        reaped = 0
                        for job_id, task_id in rows:
                            key = (job_id, task_id)
                            current_keys.add(key)
                            if task_id in live:
                                missing_counts.pop(key, None)
                                continue
                            misses = missing_counts.get(key, 0) + 1
                            missing_counts[key] = misses
                            if misses < 2:
                                continue
                            res = await db.execute(sql_text(
                                "UPDATE processing_jobs SET status = 'error', "
                                "error_message = 'Worker restarted while this job was running — re-run it', "
                                "finished_at = (now() AT TIME ZONE 'utc') "
                                "WHERE id = :id AND status = 'running' AND celery_task_id = :tid"
                            ), {"id": job_id, "tid": task_id})
                            reaped += res.rowcount or 0
                            missing_counts.pop(key, None)
                        # Drop counters for jobs that finished or resumed.
                        for key in list(missing_counts):
                            if key not in current_keys:
                                del missing_counts[key]
                        if reaped:
                            await db.commit()
                            print(f"[{_ts()}] Stale-job reaper: failed {reaped} phantom running job(s) lost to a worker restart")
            except Exception as e:
                print(f"[{_ts()}] Stale-job reaper error: {e}")
            await asyncio.sleep(120)

    reaper_task = asyncio.create_task(_reap_stale_jobs_loop())

    # ---- Overnight watchdog: auto-retry failed pipeline jobs -------------
    # Long unattended runs (bulk reindex) die to transient causes — OOM,
    # worker rebuilds (the reaper above marks those as error), Qdrant
    # timeouts. This loop requeues errored pipeline jobs up to 3 attempts,
    # so the pipeline heals itself instead of stalling until morning.
    # Worker tasks are idempotent on retry (they delete prior rows first).
    _AUTO_RETRY_TYPES = (
        "sprite", "visual_embed", "index", "scene_detect", "face_detect",
        "audio_extract", "transcribe", "diarize", "qc", "proxy", "analyze",
        "creative", "identify", "insights",
    )
    _MAX_AUTO_RETRIES = 3

    async def _auto_retry_loop():
        from sqlalchemy import text as sql_text
        from .database import AsyncSessionLocal
        from .worker_client import enqueue_job
        await asyncio.sleep(180)  # let workers come up after a stack restart
        while True:
            try:
                async with AsyncSessionLocal() as db:
                    rows = (await db.execute(sql_text(
                        "SELECT id, media_id, job_type, retry_count FROM processing_jobs "
                        "WHERE status = 'error' AND job_type = ANY(:types) "
                        "AND retry_count < :max_r "
                        "AND finished_at < (now() AT TIME ZONE 'utc') - interval '3 minutes' "
                        "AND created_at > (now() AT TIME ZONE 'utc') - interval '48 hours' "
                        "ORDER BY finished_at LIMIT 20"
                    ), {"types": list(_AUTO_RETRY_TYPES), "max_r": _MAX_AUTO_RETRIES})).fetchall()
                    requeued = 0
                    for job_id, media_id, job_type, retry_count in rows:
                        res = await db.execute(sql_text(
                            "UPDATE processing_jobs SET status = 'pending', "
                            "retry_count = retry_count + 1, error_message = NULL, "
                            "started_at = NULL, finished_at = NULL, heartbeat_at = NULL, "
                            "celery_task_id = NULL, progress = 0 "
                            "WHERE id = :id AND status = 'error'"
                        ), {"id": job_id})
                        if not (res.rowcount or 0):
                            continue
                        await db.commit()
                        try:
                            await enqueue_job(job_type, media_id, job_id)
                            requeued += 1
                        except Exception as e:
                            # Broker briefly down: put the job back to error so
                            # a later cycle retries it (attempt not consumed).
                            await db.execute(sql_text(
                                "UPDATE processing_jobs SET status = 'error', "
                                "retry_count = retry_count - 1, "
                                "error_message = :msg, finished_at = (now() AT TIME ZONE 'utc') "
                                "WHERE id = :id"
                            ), {"id": job_id, "msg": f"Auto-retry enqueue failed: {e}"})
                            await db.commit()
                    if requeued:
                        print(f"[{_ts()}] Watchdog: auto-retried {requeued} failed job(s)")
            except Exception as e:
                print(f"[{_ts()}] Watchdog error: {e}")
            await asyncio.sleep(180)

    watchdog_task = asyncio.create_task(_auto_retry_loop())

    yield


app = FastAPI(
    title="obtv-ai API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Session auth for every /api route (including the StaticFiles thumbnail
# mount, which router-level dependencies would miss).
app.middleware("http")(auth_middleware)


@app.middleware("http")
async def _lipsync_reference_size_guard(request, call_next):
    """Reject oversized lipsync-reference uploads BEFORE Starlette's multipart
    parser spools the whole body to disk — the endpoint's own size check only
    runs after spooling, so without this a multi-GB request eats the uploads
    volume before it can 400."""
    if request.method == "POST" and request.url.path.endswith("/lipsync/reference"):
        cl = request.headers.get("content-length")
        if not cl or not cl.isdigit():
            return JSONResponse(status_code=411, content={"detail": "Content-Length required"})
        if int(cl) > 510 * 1024 * 1024:
            return JSONResponse(status_code=413, content={"detail": "File too large (500 MB max)"})
    return await call_next(request)

app.include_router(auth_router.router, prefix="/api")
app.include_router(users_router.router, prefix="/api")
app.include_router(audit_router.router, prefix="/api")
app.include_router(media.router, prefix="/api")
app.include_router(folders.router, prefix="/api")
app.include_router(curator.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(ai.router, prefix="/api")
app.include_router(clips.router, prefix="/api")
app.include_router(people.router, prefix="/api")
app.include_router(insights.router, prefix="/api")
app.include_router(renders.router, prefix="/api")
app.include_router(reels.router, prefix="/api")
app.include_router(stories.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(project_chat.router, prefix="/api")
app.include_router(project_chat.cut_router, prefix="/api")
app.include_router(voice.router, prefix="/api")
app.include_router(graphics.router, prefix="/api")
app.include_router(trends.router, prefix="/api")
app.include_router(socials.router, prefix="/api")
app.include_router(ratings.router, prefix="/api")


@app.get("/api/healthz")
async def healthz():
    return {"status": "ok"}


thumbnails_dir = settings.thumbnails_dir
# Create the dir ourselves before mounting: on a fresh deployment it doesn't
# exist until a worker writes the first thumbnail, and a conditional mount
# would silently 404 every thumbnail until the api container restarts.
os.makedirs(thumbnails_dir, exist_ok=True)
app.mount("/api/thumbnails", StaticFiles(directory=thumbnails_dir), name="thumbnails")
