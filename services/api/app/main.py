import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .database import engine, Base
from .config import settings
from .routers import media, search, jobs, ai, clips


# Columns created as `json` by earlier versions must become `jsonb` so workers
# can append with the || operator. Idempotent: no-op once the type is jsonb.
_JSONB_MIGRATIONS = [
    ("processing_jobs", "logs"),
    ("face_clusters", "appearances"),
    ("ai_messages", "citations"),
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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

    try:
        from .services.qdrant_client import ensure_collections
        await ensure_collections()
    except Exception as e:
        print(f"Warning: Qdrant not available: {e}")

    os.makedirs(settings.proxies_dir, exist_ok=True)
    os.makedirs(settings.thumbnails_dir, exist_ok=True)
    os.makedirs(settings.audio_dir, exist_ok=True)

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


@app.get("/api/healthz")
async def healthz():
    return {"status": "ok"}


thumbnails_dir = settings.thumbnails_dir
if os.path.exists(thumbnails_dir):
    app.mount("/api/thumbnails", StaticFiles(directory=thumbnails_dir), name="thumbnails")
