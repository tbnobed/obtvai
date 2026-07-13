import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .database import engine, Base
from .config import settings
from .routers import media, search, jobs, ai, clips, people, insights, renders, reels


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
]


# Library-wide jobs (e.g. insights) have no media asset.
_NULLABLE_MIGRATIONS = [
    ("processing_jobs", "media_id"),
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    from sqlalchemy import text

    async with engine.begin() as conn:
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

app.include_router(media.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(ai.router, prefix="/api")
app.include_router(clips.router, prefix="/api")
app.include_router(people.router, prefix="/api")
app.include_router(insights.router, prefix="/api")
app.include_router(renders.router, prefix="/api")
app.include_router(reels.router, prefix="/api")


@app.get("/api/healthz")
async def healthz():
    return {"status": "ok"}


thumbnails_dir = settings.thumbnails_dir
if os.path.exists(thumbnails_dir):
    app.mount("/api/thumbnails", StaticFiles(directory=thumbnails_dir), name="thumbnails")
