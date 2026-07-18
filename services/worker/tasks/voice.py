"""Voice cloning: sample preparation (CPU) and XTTS-v2 speech generation (GPU)."""
import contextlib
import os
import subprocess
import time
from datetime import datetime

from app import celery_app
from db import get_session
from config import VOICES_DIR

# XTTS wants clean 24 kHz mono reference audio.
SAMPLE_RATE = 24000
MIN_SAMPLE_SECONDS = 10.0
XTTS_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"

_xtts_cache: dict = {}


def _update_sample(db, sample_id: str, **kwargs):
    from sqlalchemy import text
    set_parts = ", ".join(f"{k} = :{k}" for k in kwargs)
    db.execute(text(f"UPDATE voice_samples SET {set_parts} WHERE id = :sid"), {**kwargs, "sid": sample_id})
    db.commit()


def _update_generation(db, gen_id: str, **kwargs):
    from sqlalchemy import text
    set_parts = ", ".join(f"{k} = :{k}" for k in kwargs)
    db.execute(text(f"UPDATE voice_generations SET {set_parts} WHERE id = :gid"), {**kwargs, "gid": gen_id})
    db.commit()


def _probe_duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"ffprobe failed: {result.stderr[-300:]}")
    return float(result.stdout.strip())


@celery_app.task(bind=True, name="tasks.voice.prepare_voice_sample", queue="cpu")
def prepare_voice_sample(self, sample_id: str):
    """Cut (if segment-sourced) and normalize a voice sample to 24 kHz mono WAV."""
    db = get_session()
    try:
        from sqlalchemy import text
        row = db.execute(
            text("""
                SELECT source, media_id, start_time, end_time, raw_path
                FROM voice_samples WHERE id = :sid
            """),
            {"sid": sample_id},
        ).fetchone()
        if not row:
            return
        source, media_id, start_time, end_time, raw_path = row

        if source == "segment":
            asset = db.execute(
                text("SELECT original_path FROM media_assets WHERE id = :mid"),
                {"mid": media_id},
            ).fetchone()
            if not asset or not asset[0] or not os.path.isfile(asset[0]):
                raise RuntimeError("Source media file not found on disk")
            src = asset[0]
            cut_args = ["-ss", str(float(start_time)), "-to", str(float(end_time))]
        else:
            if not raw_path or not os.path.isfile(raw_path):
                raise RuntimeError("Uploaded audio file not found on disk")
            src = raw_path
            cut_args = []

        samples_dir = os.path.join(VOICES_DIR, "samples")
        os.makedirs(samples_dir, exist_ok=True)
        out_path = os.path.join(samples_dir, f"{sample_id}.wav")

        # Normalize: mono, 24 kHz, trim silence at both ends, loudness-normalize.
        result = subprocess.run(
            ["ffmpeg", "-y", *cut_args, "-i", src,
             "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
             # Trim leading silence, then trailing silence via reverse →
             # trim-lead → reverse. (stop_periods=1 is NOT "trim the end":
             # it cuts the output at the FIRST mid-speech pause, which
             # truncated multi-minute samples to under a second.)
             "-af", "silenceremove=start_periods=1:start_threshold=-45dB,"
                    "areverse,silenceremove=start_periods=1:start_threshold=-45dB,"
                    "areverse,loudnorm=I=-20:TP=-2",
             "-c:a", "pcm_s16le", out_path],
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg normalize failed: {result.stderr[-400:]}")

        duration = _probe_duration(out_path)
        if duration < 1.0:
            with contextlib.suppress(OSError):
                os.unlink(out_path)
            raise RuntimeError("Sample is under 1 second of audible speech after trimming")

        if raw_path and os.path.isfile(raw_path):
            with contextlib.suppress(OSError):
                os.unlink(raw_path)

        _update_sample(db, sample_id, status="ready", audio_path=out_path,
                       duration_seconds=float(duration), error_message=None, raw_path=None)
    except Exception as e:
        db.rollback()
        _update_sample(db, sample_id, status="error", error_message=str(e)[:500])
        raise
    finally:
        db.close()


def _load_xtts():
    if "tts" in _xtts_cache:
        return _xtts_cache["tts"]
    import torch
    from TTS.api import TTS

    os.environ.setdefault("COQUI_TOS_AGREED", "1")
    # torch>=2.6 defaults torch.load to weights_only=True, which rejects the
    # XTTS checkpoint's pickled config objects. Patch for the load only.
    original_load = torch.load

    def _patched_load(*args, **kwargs):
        kwargs["weights_only"] = False
        return original_load(*args, **kwargs)

    torch.load = _patched_load
    try:
        tts = TTS(XTTS_MODEL)
        if torch.cuda.is_available():
            tts = tts.to("cuda")
    finally:
        torch.load = original_load
    _xtts_cache["tts"] = tts
    return tts


def get_ready_voice_paths(db, person_id: str) -> list[str]:
    """Ready sample WAV paths for a person (used here and by dubbing)."""
    from sqlalchemy import text
    rows = db.execute(
        text("""
            SELECT audio_path FROM voice_samples
            WHERE person_id = :pid AND status = 'ready' AND audio_path IS NOT NULL
            ORDER BY duration_seconds DESC NULLS LAST
        """),
        {"pid": person_id},
    ).fetchall()
    paths = [r[0] for r in rows if r[0] and os.path.isfile(r[0])]
    total = 0.0
    for p in paths:
        with contextlib.suppress(Exception):
            total += _probe_duration(p)
    return paths if total >= MIN_SAMPLE_SECONDS else []


# Synthesis style presets for A/B tuning. "natural" = XTTS-v2 stock
# defaults (hand-tuned overrides proved worse across the board, but taste
# varies per voice — the user picks the winner and it's saved per person).
PRESET_SETTINGS = {
    "natural": {},
    "expressive": {"temperature": 0.85, "top_p": 0.9},
    "steady": {"temperature": 0.5, "top_k": 30, "top_p": 0.7},
    "warm": {"temperature": 0.75, "repetition_penalty": 7.0, "top_p": 0.85},
}


# Custom knobs the API may pass through (validated server-side).
_ALLOWED_SETTINGS = {"speed", "temperature", "top_p", "top_k", "repetition_penalty"}

# Sane finite ranges. XTTS applies speed as int(len/speed) internally, so a
# stored speed of 0/inf/NaN crashes with "cannot convert float infinity to
# integer" — clamp everything before it reaches the engine.
_SETTING_RANGES = {
    "speed": (0.5, 2.0, 1.0),
    "temperature": (0.05, 1.5, 0.75),
    "top_p": (0.05, 1.0, 0.85),
    "top_k": (1.0, 100.0, 50.0),
    "repetition_penalty": (1.0, 15.0, 5.0),
}


def _sanitize_settings(kwargs: dict) -> dict:
    import math
    clean = {}
    for k, v in kwargs.items():
        lo, hi, default = _SETTING_RANGES.get(k, (None, None, None))
        if lo is None:
            clean[k] = v
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            f = default
        if not math.isfinite(f) or f <= 0:
            f = default
        clean[k] = min(hi, max(lo, f))
    return clean


def synthesize_cloned(tts, text_value: str, language: str, speaker_wavs: list[str], out_path: str,
                      preset: str | None = None, settings: dict | None = None):
    kwargs = dict(PRESET_SETTINGS.get(preset or "natural", {}))
    if settings:
        # Custom slider values override the preset base.
        kwargs.update({k: float(v) for k, v in settings.items()
                       if k in _ALLOWED_SETTINGS and v is not None})
    kwargs = _sanitize_settings(kwargs)
    tts.tts_to_file(
        text=text_value,
        language=language,
        speaker_wav=speaker_wavs,
        file_path=out_path,
        split_sentences=True,
        **kwargs,
    )


@celery_app.task(bind=True, name="tasks.voice.generate_speech", queue="gpu")
def generate_speech(self, generation_id: str):
    db = get_session()
    try:
        from sqlalchemy import text
        row = db.execute(
            text("""
                SELECT g.person_id, g.text, g.language, g.preset, g.settings,
                       p.voice_preset, p.voice_settings
                FROM voice_generations g JOIN people p ON p.id = g.person_id
                WHERE g.id = :gid
            """),
            {"gid": generation_id},
        ).fetchone()
        if not row:
            return
        person_id, text_value, language, gen_preset, gen_settings, person_preset, person_settings = row
        # Precedence: per-generation settings > per-generation preset (tuning
        # run) > person's saved custom settings > person's saved preset.
        if gen_settings:
            preset, settings = None, gen_settings
        elif gen_preset:
            preset, settings = gen_preset, None
        else:
            preset, settings = person_preset, person_settings

        _update_generation(db, generation_id, status="running", progress=5.0)

        speaker_wavs = get_ready_voice_paths(db, person_id)
        if not speaker_wavs:
            raise RuntimeError("No ready voice samples for this person")

        _update_generation(db, generation_id, progress=15.0)
        tts = _load_xtts()
        _update_generation(db, generation_id, progress=40.0)

        gens_dir = os.path.join(VOICES_DIR, "generations")
        os.makedirs(gens_dir, exist_ok=True)
        out_path = os.path.join(gens_dir, f"{generation_id}.wav")

        started = time.monotonic()
        # Longest 1-2 clean references beat a pile of mixed recordings.
        synthesize_cloned(tts, text_value, language, speaker_wavs[:2], out_path,
                          preset=preset, settings=settings)
        elapsed = time.monotonic() - started

        duration = _probe_duration(out_path)
        _update_generation(
            db, generation_id,
            status="success", progress=100.0,
            audio_path=out_path, duration_seconds=float(duration), error_message=None,
        )
        print(f"[voice] generated {duration:.1f}s in {elapsed:.1f}s for person {person_id}")
    except Exception as e:
        db.rollback()
        _update_generation(db, generation_id, status="error", error_message=str(e)[:500])
        raise
    finally:
        db.close()
