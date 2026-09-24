"""Read-only archive playback. Generated segments live only in bounded RAM.

All URLs identify database assets, never user-supplied filesystem paths. Router
authentication is provided by the application's /api session middleware.

CPU tradeoff: independent exact seeks require re-encoding, not GOP stream-copy.
Each six-second request uses libx264 veryfast, 30fps, at most 1280px width and
two codec threads. Two jobs and two in-flight segment deliveries per API
process are allowed; additional requests fail quickly with retryable 503.
This is deliberately not a disk cache or a production capacity benchmark.
"""
import asyncio
import json
import math
import os
import re
from pathlib import Path

from fastapi import HTTPException, Request
from starlette.responses import StreamingResponse

SEGMENT_SECONDS = 6
MAX_OUTPUT = 12 * 1024 * 1024
MAX_DURATION = 7 * 24 * 3600
FORMATS = "mov,matroska,webm,avi,mxf,wav,mp3,aac,flac,ogg,mpegts,mpegvideo"
_slots = asyncio.Semaphore(2)  # per API process, including probes
_deliveries = asyncio.Semaphore(2)  # hold until slow clients finish/disconnect
NO_STORE = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


def enabled():
    return os.getenv("CURATOR_ARCHIVE_MODE", "").lower() in ("1", "true", "yes")


def roots():
    return [Path(p).resolve() for p in os.getenv("CURATOR_ARCHIVE_ROOTS", "/curator").split(os.pathsep) if p]


def contained(path):
    p = Path(path).resolve()
    return any(p.is_relative_to(root) and p != root for root in roots())


def mount_points():
    """mountinfo sees Docker bind mounts even when os.path.ismount cannot."""
    try:
        entries = Path("/proc/self/mountinfo").read_text().splitlines()
        return [Path(re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), line.split()[4]))
                for line in entries if len(line.split()) >= 5 and line.split()[4] != "/"]
    except OSError:
        return []


def validate_roots():
    configured = roots()
    mounts = mount_points()
    if not configured or any(
        not root.is_dir() or not os.access(root, os.R_OK | os.X_OK)
        or not any(root == mount or root.is_relative_to(mount) for mount in mounts)
        for root in configured
    ):
        raise HTTPException(503, "Archive mount unavailable or unreadable")


def archive_asset(asset):
    return enabled() and any(
        p and contained(p) for p in (asset.proxy_path, asset.original_path)
    )


def source(asset):
    validate_roots()
    # Prefer the linked archive proxy over a hi-res original.
    for raw in (asset.proxy_path, asset.original_path):
        if raw and contained(raw):
            p = Path(raw).resolve()
            if p.is_file():
                return p
    raise HTTPException(404, "Archive source unavailable")


def audio_sidecars(video):
    """Only this render's sidecars, not arbitrary audio in the directory."""
    match = re.match(r"^(.*)_video\.mp4$", video.name, re.I)
    if not match:
        return []
    pattern = re.compile(re.escape(match[1]) + r"_audio(\d*)\.(mp4|m4a|aac)$", re.I)
    found = []
    for p in video.parent.iterdir():
        m = pattern.fullmatch(p.name)
        if m and contained(p) and p.is_file():
            found.append((int(m[1] or 0), p.resolve()))
    if len(found) > 16:
        raise HTTPException(422, "Archive render has more than 16 audio sidecars")
    return [p for _, p in sorted(found)]


async def run_bounded(cmd, request=None, limit=MAX_OUTPUT, timeout=45):
    """Bound concurrency, bytes, wall time; reap children even on disconnect."""
    try:
        await asyncio.wait_for(_slots.acquire(), 2)
    except asyncio.TimeoutError:
        raise HTTPException(503, "Playback capacity reached", headers={"Retry-After": "2"})
    proc = None
    try:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError:
            raise HTTPException(503, "Archive playback codec service unavailable")

        async def read():
            data = bytearray()
            while True:
                chunk = await proc.stdout.read(65536)
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > limit:
                    raise HTTPException(502, "Playback output exceeded memory limit")
            if await proc.wait():
                raise HTTPException(502, "Archive media could not be decoded")
            return bytes(data)

        async def disconnected():
            while True:
                if request is not None and await request.is_disconnected():
                    raise HTTPException(499, "Playback client disconnected")
                await asyncio.sleep(.2)

        reader = asyncio.create_task(read())
        watcher = asyncio.create_task(disconnected())
        try:
            done, _ = await asyncio.wait(
                [reader, watcher], timeout=timeout, return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                raise HTTPException(504, "Archive playback timed out")
            return await next(iter(done))
        finally:
            reader.cancel()
            watcher.cancel()
            await asyncio.gather(reader, watcher, return_exceptions=True)
    finally:
        if proc is not None and proc.returncode is None:
            proc.kill()
            await proc.wait()
        _slots.release()


async def describe(asset, request=None):
    path = source(asset)
    raw = await run_bounded([
        "ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-format_whitelist", FORMATS,
        "-show_entries", "format=duration:stream=codec_type,duration",
        "-of", "json", str(path),
    ], request, limit=256 * 1024, timeout=15)
    try:
        data = json.loads(raw)
        kinds = {s["codec_type"] for s in data["streams"]}
        duration = float(data.get("format", {}).get("duration") or asset.duration_seconds or 0)
        if not math.isfinite(duration) or not 0 < duration <= MAX_DURATION:
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise HTTPException(422, "Archive has no valid playback duration")
    if not kinds.intersection({"audio", "video"}):
        raise HTTPException(415, "Archive source has no playable audio or video")
    sidecars = audio_sidecars(path) if "video" in kinds and "audio" not in kinds else []
    return path, duration, "video" in kinds, "audio" in kinds, sidecars


def playlist(duration):
    count = math.ceil(duration / SEGMENT_SECONDS)
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-PLAYLIST-TYPE:VOD",
             "#EXT-X-TARGETDURATION:6", "#EXT-X-MEDIA-SEQUENCE:0",
             "#EXT-X-INDEPENDENT-SEGMENTS"]
    for n in range(count):
        lines += [f"#EXTINF:{min(SEGMENT_SECONDS, duration - n * SEGMENT_SECONDS):.6f},",
                  f"segments/{n}.ts"]
    return "\n".join(lines + ["#EXT-X-ENDLIST", ""])


def segment_command(path, sidecars, video, audio, start, duration):
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-threads", "2",
           "-filter_threads", "1", "-filter_complex_threads", "1"]
    for p in [path, *sidecars]:
        # Accurate input seek decodes/discards up to the requested timestamp.
        # Never copy GOPs: every segment must start at its exact VOD boundary.
        cmd += ["-ss", str(start), "-protocol_whitelist", "file,pipe",
                "-format_whitelist", FORMATS, "-i", str(p)]
    if video:
        cmd += ["-map", "0:v:0", "-vf", "scale=w='min(1280,iw)':h=-2,fps=30",
                "-c:v", "libx264", "-threads", "2", "-preset", "veryfast",
                "-pix_fmt", "yuv420p", "-b:v", "2000k", "-maxrate", "2500k",
                "-bufsize", "5000k", "-bf", "0", "-g", "180", "-keyint_min", "180", "-sc_threshold", "0"]
    if sidecars:
        ins = "".join(f"[{i}:a:0]" for i in range(1, len(sidecars) + 1))
        cmd += ["-filter_complex",
                f"{ins}amix=inputs={len(sidecars)}:duration=longest:normalize=0[a]",
                "-map", "[a]"]
    elif audio:
        cmd += ["-map", "0:a:0"]
    if sidecars or audio:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "48000"]
    cmd += ["-t", str(duration), "-sn", "-dn", "-map_metadata", "-1",
            # Fixed positive origin prevents first-segment-only timestamp
            # shifting for AAC encoder priming / negative decode timestamps.
            "-output_ts_offset", str(start + 1), "-avoid_negative_ts", "disabled", "-mpegts_copyts", "1",
            "-muxdelay", "0", "-muxpreload", "0", "-f", "mpegts", "pipe:1"]
    return cmd


async def segment(asset, number, request):
    path, duration, video, audio, sidecars = await describe(asset, request)
    start = number * SEGMENT_SECONDS
    if number < 0 or start >= duration:
        raise HTTPException(416, "Segment outside asset duration")
    return await run_bounded(segment_command(
        path, sidecars, video, audio, start, min(SEGMENT_SECONDS, duration - start),
    ), request)


class _SegmentResponse(StreamingResponse):
    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            _deliveries.release()


async def segment_response(asset, number, request):
    try:
        await asyncio.wait_for(_deliveries.acquire(), 2)
    except asyncio.TimeoutError:
        raise HTTPException(503, "Playback delivery capacity reached", headers={"Retry-After": "2"})
    try:
        data = await segment(asset, number, request)
        async def chunks():
            for offset in range(0, len(data), 65536):
                yield data[offset:offset + 65536]
        return _SegmentResponse(
            chunks(), media_type="video/mp2t",
            headers={**NO_STORE, "Content-Length": str(len(data))},
        )
    except BaseException:
        _deliveries.release()
        raise