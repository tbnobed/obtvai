"""CPU-only playback ASGI entrypoint; deliberately never imports app.main.

Authentication uses the existing sessions database. Media rows are copied into
immutable scalar snapshots and the session is CLOSED before filesystem access,
probing, encoding, or streaming. No model warmup, DDL, bootstrap, or disk cache.
"""
import asyncio
import mimetypes
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select

from . import playback
from .auth import auth_middleware
from .database import AsyncSessionLocal, engine
from .models import MediaAsset


def _bounded_setting(name, default, maximum):
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be an integer between 1 and {maximum}") from None
    if not 1 <= value <= maximum:
        raise RuntimeError(f"{name} must be between 1 and {maximum}")
    return value


@asynccontextmanager
async def lifespan(_app):
    # One uvicorn process per replica. Keep FFmpeg's own two-thread bound.
    playback._slots = asyncio.Semaphore(_bounded_setting("PLAYBACK_ENCODE_JOBS", 2, 64))
    playback._deliveries = asyncio.Semaphore(_bounded_setting("PLAYBACK_DELIVERIES", 32, 512))
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(
    title="OBTV playback", lifespan=lifespan,
    docs_url=None, redoc_url=None, openapi_url=None,
    redirect_slashes=False,
)
app.middleware("http")(auth_middleware)


@dataclass(frozen=True)
class MediaSnapshot:
    id: str
    proxy_path: str | None
    original_path: str | None
    duration_seconds: float | None


async def media_snapshot(media_id: str) -> MediaSnapshot:
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(
                MediaAsset.id, MediaAsset.proxy_path,
                MediaAsset.original_path, MediaAsset.duration_seconds,
            ).where(MediaAsset.id == media_id)
        )).first()
        snapshot = MediaSnapshot(*row) if row else None
    # The context exit above returns the DB connection before all media work.
    if snapshot is None:
        raise HTTPException(404, "Media not found")
    return snapshot


@app.get("/api/healthz")
async def healthz():
    return {"status": "ok", "service": "playback"}


@app.get("/api/media/{id}/playback")
async def playback_info(id: str, request: Request):
    asset = await media_snapshot(id)
    info = {"type": "file", "url": f"/api/media/{id}/stream"}
    if playback.archive_asset(asset):
        mime = mimetypes.guess_type(str(playback.source(asset)))[0] or ""
        if mime.startswith("image/"):
            info["type"] = "image"
        else:
            _, duration, video, audio, sides = await playback.describe(asset, request)
            info = {
                "type": "hls", "url": f"/api/media/{id}/hls.m3u8",
                "duration": duration, "hasVideo": video,
                "hasAudio": audio or bool(sides),
            }
    # Ordinary stream/image/download endpoints remain on the main API.
    return JSONResponse(info, headers=playback.NO_STORE)


@app.get("/api/media/{id}/hls.m3u8")
async def archive_playlist(id: str, request: Request):
    asset = await media_snapshot(id)
    if not playback.archive_asset(asset):
        raise HTTPException(404, "Archive playback unavailable")
    _, duration, _, _, _ = await playback.describe(asset, request)
    return Response(
        playback.playlist(duration), media_type="application/vnd.apple.mpegurl",
        headers=playback.NO_STORE,
    )


@app.get("/api/media/{id}/segments/{number}.ts")
async def archive_segment(id: str, number: int, request: Request):
    if request.headers.get("range"):
        raise HTTPException(416, "Generated segments use time-based seeking, not byte ranges")
    if number < 0:
        raise HTTPException(416, "Segment outside asset duration")
    asset = await media_snapshot(id)
    if not playback.archive_asset(asset):
        raise HTTPException(404, "Archive playback unavailable")
    return await playback.segment_response(asset, number, request)