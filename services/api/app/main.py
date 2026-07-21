import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .database import engine, Base
from .config import settings
from .routers import media, search, jobs, ai, clips, people, insights, renders, reels, stories, projects, voice, graphics, trends, ratings, auth as auth_router, users as users_router
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
    ("media_assets", "synopsis", "TEXT"),
    ("media_assets", "key_moments", "JSONB"),
    ("media_assets", "topics", "JSONB"),
    ("media_assets", "highlight_url", "TEXT"),
    ("media_assets", "social_scores", "JSONB"),
    ("media_assets", "translated_languages", "JSONB"),
    ("media_assets", "dubbed_languages", "JSONB"),
    ("transcript_segments", "translations", "JSONB"),
    ("media_assets", "speaker_embeddings", "JSONB"),
    ("face_clusters", "embedding", "JSONB"),
    ("reel_jobs", "media_id", "TEXT"),
    ("media_assets", "creative", "JSONB"),
    ("clip_lists", "project_id", "TEXT"),
    ("render_jobs", "project_id", "TEXT"),
    ("reel_jobs", "project_id", "TEXT"),
    ("story_jobs", "project_id", "TEXT"),
    ("projects", "status", "TEXT NOT NULL DEFAULT 'active'"),
    ("projects", "media_ids", "JSONB"),
    ("reel_jobs", "target_duration_seconds", "DOUBLE PRECISION"),
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
        for table, column, coltype in _COLUMN_MIGRATIONS:
            await conn.execute(text(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {coltype}"
            ))
        for table, column in _NULLABLE_MIGRATIONS:
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

        # Same singleton guarantee for library-wide trends refresh jobs.
        await conn.execute(text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_processing_jobs_active_trends
            ON processing_jobs (job_type)
            WHERE job_type = 'trends' AND status IN ('pending', 'running')
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

app.include_router(auth_router.router, prefix="/api")
app.include_router(users_router.router, prefix="/api")
app.include_router(media.router, prefix="/api")
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
app.include_router(voice.router, prefix="/api")
app.include_router(graphics.router, prefix="/api")
app.include_router(trends.router, prefix="/api")
app.include_router(ratings.router, prefix="/api")


@app.get("/api/healthz")
async def healthz():
    return {"status": "ok"}


thumbnails_dir = settings.thumbnails_dir
if os.path.exists(thumbnails_dir):
    app.mount("/api/thumbnails", StaticFiles(directory=thumbnails_dir), name="thumbnails")
