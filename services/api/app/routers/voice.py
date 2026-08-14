import asyncio
import os
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from ..database import get_db
from ..models import Person, MediaAsset, VoiceSample, VoiceGeneration
from ..schemas import (
    VoiceProfileOut,
    VoiceSampleOut,
    VoiceSampleFromSegmentIn,
    VoiceSpeakIn,
    VoiceTuneIn,
    VoicePresetIn,
    VoiceSettingsIn,
    VoiceGenerationOut,
)
from .. import worker_client

router = APIRouter(tags=["voice"])

MIN_SAMPLE_SECONDS = 10.0
MAX_SEGMENT_SECONDS = 60.0
VOICES_DIR = os.getenv("VOICES_DIR", "/artifacts/voices")
ALLOWED_UPLOAD_EXT = {".wav", ".mp3", ".m4a", ".flac", ".ogg"}
XTTS_LANGUAGES = {
    "en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru",
    "nl", "cs", "ar", "zh-cn", "ja", "hu", "ko", "hi",
}
# Must match PRESET_SETTINGS in services/worker/tasks/voice.py
VOICE_PRESETS = ["natural", "expressive", "steady", "warm"]

# Allowed ranges for custom synthesis settings (key: (min, max))
SETTINGS_RANGES = {
    "speed": (0.7, 1.3),
    "temperature": (0.2, 1.2),
    "top_p": (0.3, 1.0),
    "repetition_penalty": (1.5, 12.0),
}


def _validate_settings(body: VoiceSettingsIn) -> dict | None:
    """Return a clean settings dict, or None if every field is empty."""
    out = {}
    for key, (lo, hi) in SETTINGS_RANGES.items():
        value = getattr(body, key)
        if value is None:
            continue
        if not (lo <= value <= hi):
            raise HTTPException(status_code=400, detail=f"{key} must be between {lo} and {hi}")
        out[key] = float(value)
    engine = (getattr(body, "engine", None) or "").strip().lower()
    if engine:
        if engine not in ("turbo", "chatterbox", "qwen3", "xtts"):
            raise HTTPException(status_code=400,
                                detail="engine must be turbo, chatterbox, qwen3 or xtts")
        out["engine"] = engine
    return out or None


def _sample_out(s: VoiceSample) -> VoiceSampleOut:
    return VoiceSampleOut(
        id=s.id,
        person_id=s.person_id,
        source=s.source,
        status=s.status,
        media_id=s.media_id,
        filename=s.filename,
        start_time=s.start_time,
        end_time=s.end_time,
        duration_seconds=s.duration_seconds,
        error_message=s.error_message,
        created_at=s.created_at,
    )


def _gen_out(g: VoiceGeneration) -> VoiceGenerationOut:
    return VoiceGenerationOut(
        id=g.id,
        person_id=g.person_id,
        text=g.text,
        language=g.language,
        status=g.status,
        progress=float(g.progress or 0),
        duration_seconds=g.duration_seconds,
        error_message=g.error_message,
        created_at=g.created_at,
        preset=g.preset,
        settings=g.settings,
        video_status=g.video_status,
        video_error=g.video_error,
    )


async def _get_person(db: AsyncSession, person_id: str) -> Person:
    person = (await db.execute(select(Person).where(Person.id == person_id))).scalar_one_or_none()
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    return person


async def _profile(db: AsyncSession, person_id: str, person: Person | None = None) -> VoiceProfileOut:
    if person is None:
        person = (await db.execute(select(Person).where(Person.id == person_id))).scalar_one_or_none()
    ref = getattr(person, "lipsync_reference_path", None)
    samples = (
        (await db.execute(
            select(VoiceSample)
            .where(VoiceSample.person_id == person_id)
            .order_by(VoiceSample.created_at)
        )).scalars().all()
    )
    total = sum(float(s.duration_seconds or 0) for s in samples if s.status == "ready")
    return VoiceProfileOut(
        person_id=person_id,
        ready=total >= MIN_SAMPLE_SECONDS,
        total_sample_seconds=total,
        min_sample_seconds=MIN_SAMPLE_SECONDS,
        samples=[_sample_out(s) for s in samples],
        has_lipsync_reference=bool(ref and os.path.isfile(ref)),
    )


@router.get("/people/{id}/voice", response_model=VoiceProfileOut)
async def get_voice_profile(id: str, db: AsyncSession = Depends(get_db)):
    await _get_person(db, id)
    return await _profile(db, id)


@router.post("/people/{id}/voice/samples", response_model=VoiceSampleOut, status_code=202)
async def add_voice_sample(id: str, body: VoiceSampleFromSegmentIn, db: AsyncSession = Depends(get_db)):
    await _get_person(db, id)
    asset = (await db.execute(select(MediaAsset).where(MediaAsset.id == body.media_id))).scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Media asset not found")
    if body.start_time < 0 or body.end_time <= body.start_time:
        raise HTTPException(status_code=400, detail="Invalid segment range")
    if body.end_time - body.start_time > MAX_SEGMENT_SECONDS:
        raise HTTPException(status_code=400, detail=f"Segment capped at {int(MAX_SEGMENT_SECONDS)} seconds")

    sample = VoiceSample(
        person_id=id,
        source="segment",
        status="pending",
        media_id=asset.id,
        filename=asset.filename,
        start_time=float(body.start_time),
        end_time=float(body.end_time),
    )
    db.add(sample)
    await db.commit()
    await db.refresh(sample)
    await worker_client.enqueue_voice_sample(sample.id)
    return _sample_out(sample)


@router.post("/people/{id}/voice/samples/upload", response_model=VoiceSampleOut, status_code=202)
async def upload_voice_sample(id: str, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    await _get_person(db, id)
    original_name = os.path.basename(file.filename or "sample.wav")
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in ALLOWED_UPLOAD_EXT:
        raise HTTPException(status_code=400, detail="Unsupported file type — use wav, mp3, m4a, flac, or ogg")

    raw_dir = os.path.join(VOICES_DIR, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", original_name)
    raw_path = os.path.join(raw_dir, f"{uuid.uuid4()}_{safe_name}")
    size = 0
    with open(raw_path, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > 500 * 1024 * 1024:
                out.close()
                os.unlink(raw_path)
                raise HTTPException(status_code=400, detail="File too large (500 MB max)")
            out.write(chunk)
    if size == 0:
        os.unlink(raw_path)
        raise HTTPException(status_code=400, detail="Empty file")

    sample = VoiceSample(
        person_id=id,
        source="upload",
        status="pending",
        filename=original_name,
        raw_path=raw_path,
    )
    db.add(sample)
    await db.commit()
    await db.refresh(sample)
    await worker_client.enqueue_voice_sample(sample.id)
    return _sample_out(sample)


ALLOWED_VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
_VIDEO_MIME = {
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime",
    ".webm": "video/webm", ".mkv": "video/x-matroska",
}


def _normalize_reference(src: str, dst: str) -> bool:
    """Transcode a reference video to browser-playable h264 mp4, trimmed to
    the 30s the lipsync render uses. Returns False on failure."""
    import subprocess
    try:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-t", "30", "-i", src,
             # Keep full HD: the lipsync output inherits this file's
             # resolution, so never downscale below 1920 wide.
             "-vf", "scale='min(1920,iw)':-2", "-an",
             "-c:v", "libx264", "-preset", "fast", "-crf", "18",
             "-movflags", "+faststart", dst],
            capture_output=True, text=True, timeout=600)
    except Exception:
        return False
    return proc.returncode == 0 and os.path.isfile(dst)


def _probe_video(path: str) -> float:
    """Return the duration of a real video file, or raise ValueError if the
    file has no decodable video stream."""
    import json as _json
    import subprocess
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", "-show_format", path],
            capture_output=True, text=True, timeout=60)
        info = _json.loads(proc.stdout or "{}")
    except Exception:
        raise ValueError("Could not read the file")
    if proc.returncode != 0 or not any(
            s.get("codec_type") == "video" for s in info.get("streams", [])):
        raise ValueError("Not a playable video file")
    try:
        return float(info.get("format", {}).get("duration") or 0)
    except (TypeError, ValueError):
        return 0.0


@router.post("/people/{id}/lipsync/reference", response_model=VoiceProfileOut, status_code=201)
async def upload_lipsync_reference(id: str, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    """Upload a reference video of the person's face for lipsync renders.
    Takes priority over automatically-selected library footage."""
    person = await _get_person(db, id)
    original_name = os.path.basename(file.filename or "reference.mp4")
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in ALLOWED_VIDEO_EXT:
        raise HTTPException(status_code=400, detail="Unsupported file type — use mp4, mov, m4v, webm, or mkv")

    ref_dir = os.path.join(VOICES_DIR, "references")
    os.makedirs(ref_dir, exist_ok=True)
    # Always normalized to browser-playable h264 mp4 (mov/mkv won't play in
    # the preview) and trimmed to the 30s the lipsync render actually uses.
    ref_path = os.path.join(ref_dir, f"{id}.mp4")
    tmp_path = os.path.join(ref_dir, f".{id}{ext}.upload")
    norm_path = os.path.join(ref_dir, f".{id}.norm.mp4")
    size = 0
    try:
        with open(tmp_path, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > 500 * 1024 * 1024:
                    raise HTTPException(status_code=400, detail="File too large (500 MB max)")
                out.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="Empty file")
        try:
            duration = _probe_video(tmp_path)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if duration < 2.0:
            raise HTTPException(
                status_code=400,
                detail="Reference video must be at least 2 seconds (only the first 30s are used)")
        ok = await asyncio.to_thread(_normalize_reference, tmp_path, norm_path)
        if not ok:
            raise HTTPException(status_code=400, detail="Could not convert the video — try an mp4")
        os.replace(norm_path, ref_path)
    finally:
        for p in (tmp_path, norm_path):
            if os.path.exists(p):
                os.unlink(p)

    old = person.lipsync_reference_path
    if old and old != ref_path and os.path.isfile(old):
        try:
            os.unlink(old)
        except OSError:
            pass
    person.lipsync_reference_path = ref_path
    await db.commit()
    return await _profile(db, id, person)


@router.delete("/people/{id}/lipsync/reference", status_code=204)
async def delete_lipsync_reference(id: str, db: AsyncSession = Depends(get_db)):
    person = await _get_person(db, id)
    path = person.lipsync_reference_path
    if path and os.path.isfile(path):
        try:
            os.unlink(path)
        except OSError:
            pass
    person.lipsync_reference_path = None
    await db.commit()


@router.get("/people/{id}/lipsync/reference")
async def stream_lipsync_reference(id: str, db: AsyncSession = Depends(get_db)):
    person = await _get_person(db, id)
    path = person.lipsync_reference_path
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="No reference video uploaded")
    # References are normalized to h264 mp4 on upload; self-heal any stored
    # before normalization existed (raw .mov/.mkv named by original ext).
    if not path.lower().endswith(".mp4"):
        fixed = os.path.join(os.path.dirname(path), f"{id}.mp4")
        norm_tmp = fixed + ".norm"
        ok = await asyncio.to_thread(_normalize_reference, path, norm_tmp)
        if ok:
            os.replace(norm_tmp, fixed)
            try:
                os.unlink(path)
            except OSError:
                pass
            person.lipsync_reference_path = fixed
            await db.commit()
            path = fixed
        else:
            if os.path.exists(norm_tmp):
                os.unlink(norm_tmp)
            ext = os.path.splitext(path)[1].lower()
            return FileResponse(path, media_type=_VIDEO_MIME.get(ext, "video/mp4"))
    return FileResponse(path, media_type="video/mp4")


@router.delete("/voice/samples/{id}", status_code=204)
async def delete_voice_sample(id: str, db: AsyncSession = Depends(get_db)):
    sample = (await db.execute(select(VoiceSample).where(VoiceSample.id == id))).scalar_one_or_none()
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")
    for path in (sample.audio_path, sample.raw_path):
        if path and os.path.isfile(path):
            try:
                os.unlink(path)
            except OSError:
                pass
    await db.delete(sample)
    await db.commit()


@router.get("/voice/samples/{id}/audio")
async def stream_voice_sample(id: str, db: AsyncSession = Depends(get_db)):
    sample = (await db.execute(select(VoiceSample).where(VoiceSample.id == id))).scalar_one_or_none()
    if not sample or sample.status != "ready" or not sample.audio_path or not os.path.isfile(sample.audio_path):
        raise HTTPException(status_code=404, detail="Sample audio not available")
    return FileResponse(sample.audio_path, media_type="audio/wav")


@router.post("/people/{id}/voice/speak", response_model=VoiceGenerationOut, status_code=202)
async def create_voice_generation(id: str, body: VoiceSpeakIn, db: AsyncSession = Depends(get_db)):
    await _get_person(db, id)
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text required")
    if len(text) > 2000:
        raise HTTPException(status_code=400, detail="Text capped at 2000 characters")
    language = (body.language or "en").strip().lower()
    if language not in XTTS_LANGUAGES:
        raise HTTPException(status_code=400, detail=f"Unsupported language '{language}'")

    profile = await _profile(db, id)
    if not profile.ready:
        raise HTTPException(
            status_code=409,
            detail=f"Voice profile not ready — add at least {int(MIN_SAMPLE_SECONDS)}s of clean samples",
        )

    settings = _validate_settings(body.settings) if body.settings else None
    if body.speed is not None:
        if not (0.5 <= body.speed <= 2.0):
            raise HTTPException(status_code=400, detail="speed must be between 0.5 and 2.0")
        settings = {**(settings or {}), "speed": float(body.speed)}
    if body.target_seconds is not None:
        if not (1.0 <= body.target_seconds <= 3600.0):
            raise HTTPException(status_code=400, detail="target_seconds must be between 1 and 3600")
        # Stored alongside synthesis settings; the worker pops it out and
        # time-stretches the finished audio to match.
        settings = {**(settings or {}), "target_seconds": float(body.target_seconds)}
    gen = VoiceGeneration(
        person_id=id, text=text, language=language,
        status="pending", progress=0.0, settings=settings,
    )
    db.add(gen)
    await db.commit()
    await db.refresh(gen)
    await worker_client.enqueue_voice_speak(gen.id)
    return _gen_out(gen)


@router.post("/voice/generations/{id}/lipsync", response_model=VoiceGenerationOut, status_code=202)
async def create_lipsync_video(id: str, db: AsyncSession = Depends(get_db)):
    """Queue a LatentSync lipsync video render for a finished voice generation:
    the person (from a reference clip of their footage) speaks the generated audio."""
    gen = (await db.execute(select(VoiceGeneration).where(VoiceGeneration.id == id))).scalar_one_or_none()
    if not gen:
        raise HTTPException(status_code=404, detail="Generation not found")
    if gen.status != "success" or not gen.audio_path:
        raise HTTPException(status_code=409, detail="Generate the audio first")
    if gen.video_status in ("pending", "running"):
        raise HTTPException(status_code=409, detail="Lipsync video already in progress")
    max_secs = float(os.environ.get("LIPSYNC_MAX_SECONDS", "120"))
    if gen.duration_seconds and gen.duration_seconds > max_secs:
        raise HTTPException(
            status_code=400,
            detail=f"Lipsync is capped at {int(max_secs)}s of audio — diffusion runs per frame "
                   "and longer clips would occupy a GPU for hours",
        )
    gen.video_status = "pending"
    gen.video_error = None
    gen.video_path = None
    await db.commit()
    await db.refresh(gen)
    await worker_client.enqueue_voice_lipsync(gen.id)
    return _gen_out(gen)


@router.get("/voice/generations/{id}/video")
async def stream_lipsync_video(id: str, db: AsyncSession = Depends(get_db)):
    gen = (await db.execute(select(VoiceGeneration).where(VoiceGeneration.id == id))).scalar_one_or_none()
    if not gen or gen.video_status != "success" or not gen.video_path or not os.path.isfile(gen.video_path):
        raise HTTPException(status_code=404, detail="Lipsync video not available")
    return FileResponse(gen.video_path, media_type="video/mp4")


@router.post("/people/{id}/voice/tune", response_model=list[VoiceGenerationOut], status_code=202)
async def tune_voice(id: str, body: VoiceTuneIn, db: AsyncSession = Depends(get_db)):
    """Queue the same text once per synthesis style so the user can A/B them."""
    await _get_person(db, id)
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text required")
    if len(text) > 400:
        raise HTTPException(status_code=400, detail="Keep tuning text under 400 characters")
    language = (body.language or "en").strip().lower()
    if language not in XTTS_LANGUAGES:
        raise HTTPException(status_code=400, detail=f"Unsupported language '{language}'")

    profile = await _profile(db, id)
    if not profile.ready:
        raise HTTPException(
            status_code=409,
            detail=f"Voice profile not ready — add at least {int(MIN_SAMPLE_SECONDS)}s of clean samples",
        )

    gens = []
    for preset in VOICE_PRESETS:
        gen = VoiceGeneration(
            person_id=id, text=text, language=language,
            status="pending", progress=0.0, preset=preset,
        )
        db.add(gen)
        gens.append(gen)
    await db.commit()
    for gen in gens:
        await db.refresh(gen)
        await worker_client.enqueue_voice_speak(gen.id)
    return [_gen_out(g) for g in gens]


@router.put("/people/{id}/voice/preset", status_code=204)
async def set_voice_preset(id: str, body: VoicePresetIn, db: AsyncSession = Depends(get_db)):
    person = await _get_person(db, id)
    preset = body.preset.strip().lower()
    if preset not in VOICE_PRESETS:
        raise HTTPException(status_code=400, detail=f"Unknown preset. Choose one of: {', '.join(VOICE_PRESETS)}")
    person.voice_preset = preset
    person.voice_settings = None  # explicit preset choice clears custom overrides
    await db.commit()


@router.put("/people/{id}/voice/settings", status_code=204)
async def set_voice_settings(id: str, body: VoiceSettingsIn, db: AsyncSession = Depends(get_db)):
    """Save custom synthesis settings; an all-null body clears them."""
    person = await _get_person(db, id)
    person.voice_settings = _validate_settings(body)
    await db.commit()


@router.get("/people/{id}/voice/generations", response_model=list[VoiceGenerationOut])
async def list_voice_generations(id: str, db: AsyncSession = Depends(get_db)):
    gens = (
        (await db.execute(
            select(VoiceGeneration)
            .where(VoiceGeneration.person_id == id)
            .order_by(VoiceGeneration.created_at.desc())
        )).scalars().all()
    )
    return [_gen_out(g) for g in gens]


@router.delete("/voice/generations/{id}", status_code=204)
async def delete_voice_generation(id: str, db: AsyncSession = Depends(get_db)):
    gen = (await db.execute(select(VoiceGeneration).where(VoiceGeneration.id == id))).scalar_one_or_none()
    if not gen:
        raise HTTPException(status_code=404, detail="Generation not found")
    if gen.audio_path and os.path.isfile(gen.audio_path):
        try:
            os.unlink(gen.audio_path)
        except OSError:
            pass
    await db.delete(gen)
    await db.commit()


@router.get("/voice/generations/{id}/audio")
async def stream_voice_generation(id: str, db: AsyncSession = Depends(get_db)):
    gen = (await db.execute(select(VoiceGeneration).where(VoiceGeneration.id == id))).scalar_one_or_none()
    if not gen or gen.status != "success" or not gen.audio_path or not os.path.isfile(gen.audio_path):
        raise HTTPException(status_code=404, detail="Generation audio not available")
    return FileResponse(gen.audio_path, media_type="audio/wav")
