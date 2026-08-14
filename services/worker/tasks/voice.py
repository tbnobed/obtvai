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

    from tasks.gpu_mem import load_with_oom_retry

    def _load():
        tts = TTS(XTTS_MODEL)
        if torch.cuda.is_available():
            tts = tts.to("cuda")
        return tts

    torch.load = _patched_load
    try:
        tts = load_with_oom_retry(XTTS_MODEL, _load)
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


# Custom knobs the API may pass through (validated server-side). "engine" is
# a dispatch selector, not a synthesis kwarg — every synthesis call must pop
# or skip it.
_ALLOWED_SETTINGS = {"speed", "temperature", "top_p", "top_k", "repetition_penalty", "engine"}

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
        f = min(hi, max(lo, f))
        # transformers requires top_k to be a strictly positive *int*; a float
        # like 30.0 raises ValueError deep inside XTTS generation.
        clean[k] = int(round(f)) if k == "top_k" else f
    return clean


def synthesize_cloned(tts, text_value: str, language: str, speaker_wavs: list[str], out_path: str,
                      preset: str | None = None, settings: dict | None = None):
    kwargs = dict(PRESET_SETTINGS.get(preset or "natural", {}))
    if settings:
        # Custom slider values override the preset base.
        kwargs.update({k: float(v) for k, v in settings.items()
                       if k in _ALLOWED_SETTINGS and k != "engine" and v is not None})
    kwargs = _sanitize_settings(kwargs)
    tts.tts_to_file(
        text=text_value,
        language=language,
        speaker_wav=speaker_wavs,
        file_path=out_path,
        split_sentences=True,
        **kwargs,
    )


_turbo_cache: dict = {}
_qwen3_cache: dict = {}

# Qwen3-TTS language names (its API takes full names, not codes).
_QWEN3_LANGS = {"en": "English", "zh": "Chinese", "ja": "Japanese",
                "ko": "Korean", "de": "German", "fr": "French",
                "ru": "Russian", "pt": "Portuguese", "es": "Spanish",
                "it": "Italian"}


def _load_chatterbox_turbo():
    """Chatterbox-Turbo: English-only successor to Chatterbox — cleaner
    prosody, less VRAM (350M), same generate() shape."""
    if "model" in _turbo_cache:
        return _turbo_cache["model"]
    import torch
    from chatterbox.tts_turbo import ChatterboxTurboTTS
    device = "cuda" if torch.cuda.is_available() else "cpu"
    from tasks.gpu_mem import load_with_oom_retry
    model = load_with_oom_retry(
        "chatterbox-turbo", lambda: ChatterboxTurboTTS.from_pretrained(device=device)
    )
    _turbo_cache["model"] = model
    return model


def _load_qwen3_tts():
    """Qwen3-TTS voice-clone model. snapshot_download first — from_pretrained
    against a remote repo can spawn subprocesses that crash under Celery
    prefork (daemonic children)."""
    if "model" in _qwen3_cache:
        return _qwen3_cache["model"]
    import torch
    from huggingface_hub import snapshot_download
    from qwen_tts import Qwen3TTSModel
    repo = os.environ.get("QWEN3_TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-Base")
    local = snapshot_download(repo)
    dev = "cuda:0" if torch.cuda.is_available() else "cpu"
    from tasks.gpu_mem import load_with_oom_retry
    model = load_with_oom_retry(
        "qwen3-tts",
        lambda: Qwen3TTSModel.from_pretrained(
            local, device_map=dev,
            dtype=torch.bfloat16 if dev != "cpu" else torch.float32),
    )
    _qwen3_cache["model"] = model
    return model


def _ref_transcript(wav_path: str) -> str | None:
    """Transcript of a reference wav for Qwen3 cloning (much better similarity
    than x-vector-only mode). Cached in a sidecar .txt next to the sample."""
    side = wav_path + ".txt"
    try:
        if os.path.exists(side):
            return open(side, encoding="utf-8").read().strip() or None
    except OSError:
        pass
    try:
        import torch
        from faster_whisper import WhisperModel
        device = "cuda" if torch.cuda.is_available() else "cpu"
        compute = "float16" if device == "cuda" else "int8"
        from tasks.gpu_mem import load_with_oom_retry
        model = load_with_oom_retry(
            "whisper-ref",
            lambda: WhisperModel("small", device=device, compute_type=compute))
        segs, _ = model.transcribe(wav_path, beam_size=1, vad_filter=True,
                                   condition_on_previous_text=False)
        text_out = " ".join(s.text.strip() for s in segs).strip()
        del model
        if text_out:
            with open(side, "w", encoding="utf-8") as f:
                f.write(text_out)
            return text_out
    except Exception as e:
        print(f"[voice] reference transcription failed: {e}")
    return None


def _ffmpeg_atempo(path: str, speed: float):
    """Pitch-preserving speed change in place (speed already clamped 0.5-2)."""
    import subprocess
    tmp = path + ".spd.wav"
    subprocess.run(["ffmpeg", "-y", "-i", path, "-filter:a", f"atempo={speed}",
                    "-c:a", "pcm_s16le", tmp], check=True, capture_output=True)
    os.replace(tmp, path)


def _find_reference_clip(db, person_id: str) -> tuple[str, float, float]:
    """Pick footage of the person speaking to use as the MiniMax reference
    video: (media file path, start, end). Prefers the longest footage-based
    voice sample; falls back to the person's first spoken appearance. An
    explicitly uploaded reference video always wins."""
    from sqlalchemy import text
    ref = db.execute(
        text("SELECT lipsync_reference_path FROM people WHERE id = :pid"),
        {"pid": person_id},
    ).scalar()
    if ref and os.path.isfile(ref):
        dur = _probe_duration(ref)
        if dur and dur >= 2.0:
            return ref, 0.0, min(float(dur), 30.0)
    rows = db.execute(
        text("""
            SELECT m.original_path, s.start_time, s.end_time
            FROM voice_samples s JOIN media_assets m ON m.id = s.media_id
            WHERE s.person_id = :pid AND s.source = 'segment'
              AND s.media_id IS NOT NULL
              AND s.start_time IS NOT NULL AND s.end_time IS NOT NULL
            ORDER BY (s.end_time - s.start_time) DESC
        """),
        {"pid": person_id},
    ).fetchall()
    for path, start, end in rows:
        if path and os.path.isfile(path) and (end - start) >= 2.0:
            return path, float(start), float(end)
    rows = db.execute(
        text("""
            SELECT m.original_path, a.first_spoken_at
            FROM person_appearances a JOIN media_assets m ON m.id = a.media_id
            WHERE a.person_id = :pid AND a.first_spoken_at IS NOT NULL
            ORDER BY a.speaking_seconds DESC NULLS LAST
        """),
        {"pid": person_id},
    ).fetchall()
    for path, start in rows:
        if path and os.path.isfile(path):
            return path, float(start), float(start) + 10.0
    raise RuntimeError(
        "No footage of this person available for the reference clip — "
        "add a voice sample cut from footage first")


_LATENTSYNC_DIR = "/opt/latentsync"
_LATENTSYNC_PY = "/opt/latentsync-venv/bin/python"
_LATENTSYNC_CKPT_DIR = os.path.join(
    os.environ.get("HF_HOME") or os.path.expanduser("~/.cache"), "latentsync-checkpoints")


def _ensure_latentsync_checkpoints() -> str:
    """Download LatentSync 1.6 weights (~5GB) into the persistent models cache
    on first use, and point the repo's relative checkpoints/ dir at them (the
    unet config references checkpoints/whisper/tiny.pt relative to the repo).

    Both GPU workers share the models_cache volume, so the download is
    serialized with a cross-container flock and published atomically (download
    to a temp dir, validate, rename) so a partial download can never be used."""
    import fcntl
    import shutil
    from huggingface_hub import snapshot_download

    unet = os.path.join(_LATENTSYNC_CKPT_DIR, "latentsync_unet.pt")
    whisper = os.path.join(_LATENTSYNC_CKPT_DIR, "whisper", "tiny.pt")
    if not (os.path.isfile(unet) and os.path.isfile(whisper)):
        os.makedirs(os.path.dirname(_LATENTSYNC_CKPT_DIR), exist_ok=True)
        lock_path = _LATENTSYNC_CKPT_DIR + ".lock"
        with open(lock_path, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                # Re-check under the lock — the other worker may have finished.
                if not (os.path.isfile(unet) and os.path.isfile(whisper)):
                    print("[voice] downloading LatentSync 1.6 checkpoints (first run, ~5GB)")
                    tmp_dir = _LATENTSYNC_CKPT_DIR + ".tmp"
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                    snapshot_download(
                        "ByteDance/LatentSync-1.6",
                        allow_patterns=["latentsync_unet.pt", "whisper/tiny.pt"],
                        local_dir=tmp_dir,
                    )
                    for rel in ("latentsync_unet.pt", os.path.join("whisper", "tiny.pt")):
                        p = os.path.join(tmp_dir, rel)
                        if not os.path.isfile(p) or os.path.getsize(p) < 1_000_000:
                            raise RuntimeError(f"LatentSync checkpoint download incomplete: {rel}")
                    shutil.rmtree(_LATENTSYNC_CKPT_DIR, ignore_errors=True)
                    os.rename(tmp_dir, _LATENTSYNC_CKPT_DIR)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
    link = os.path.join(_LATENTSYNC_DIR, "checkpoints")
    try:
        os.symlink(_LATENTSYNC_CKPT_DIR, link)
    except FileExistsError:
        pass
    return unet


@celery_app.task(bind=True, name="tasks.voice.lipsync_video", queue="gpu")
def lipsync_video(self, generation_id: str):
    """Render a lipsynced video locally with LatentSync 1.6: a reference clip
    of the person's footage + the generated cloned-voice audio."""
    import subprocess
    import tempfile
    from sqlalchemy import text

    db = get_session()

    def _vid(**kw):
        sets = ", ".join(f"{k} = :{k}" for k in kw)
        db.execute(text(f"UPDATE voice_generations SET {sets} WHERE id = :gid"),
                   {**kw, "gid": generation_id})
        db.commit()

    try:
        row = db.execute(
            text("SELECT person_id, text, audio_path, duration_seconds FROM voice_generations WHERE id = :gid"),
            {"gid": generation_id},
        ).fetchone()
        if not row:
            return
        person_id, text_value, audio_path, audio_dur = row
        if not audio_path or not os.path.isfile(audio_path):
            raise RuntimeError("Generated audio file is missing")
        audio_dur = float(audio_dur or _probe_duration(audio_path))
        max_secs = float(os.environ.get("LIPSYNC_MAX_SECONDS", "120"))
        if audio_dur > max_secs:
            raise RuntimeError(
                f"Lipsync is capped at {int(max_secs)}s of audio ({audio_dur:.0f}s requested) — "
                "512px diffusion runs per frame and longer clips would occupy a GPU for hours")

        _vid(video_status="running", video_error=None)
        unet_ckpt = _ensure_latentsync_checkpoints()

        ref_path, ref_start, ref_end = _find_reference_clip(db, person_id)
        with tempfile.TemporaryDirectory() as workdir:
            # Reference clip normalized to what LatentSync expects: 25fps
            # h264, no audio track needed. No manual looping — LatentSync
            # itself loops the reference frames when the audio is longer.
            ref_len = max(2.0, min(30.0, ref_end - ref_start))
            ref_mp4 = os.path.join(workdir, "ref.mp4")
            # Keep the reference near source resolution (cap 1920): LatentSync
            # only diffuses the 512px face crop, but the pasted-back frame and
            # the affine crop quality both come from this input.
            max_w = int(os.environ.get("LIPSYNC_MAX_WIDTH", "1920"))
            subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{ref_start:.3f}", "-t", f"{ref_len:.3f}",
                 "-i", ref_path,
                 "-vf", f"scale='min({max_w},iw)':-2", "-r", "25", "-an",
                 "-c:v", "libx264", "-preset", "fast", "-crf", "18", ref_mp4],
                check=True, capture_output=True)

            out_tmp = os.path.join(workdir, "out.mp4")
            env = {
                **os.environ,
                # LatentSync checkpoints predate torch 2.6's weights_only
                # default; force the old torch.load behavior in the venv.
                "TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD": "1",
            }
            # Quality-first defaults (tunable via env): more denoising steps
            # and no DeepCache — DeepCache reuses cached U-Net features across
            # steps, which visibly softens teeth/lips. ~4-5x slower than the
            # old 20-step DeepCache config, so the timeout scales too.
            steps = os.environ.get("LIPSYNC_INFERENCE_STEPS", "50")
            guidance = os.environ.get("LIPSYNC_GUIDANCE_SCALE", "1.5")
            cmd = [_LATENTSYNC_PY, "-m", "scripts.inference",
                   "--unet_config_path", "configs/unet/stage2_512.yaml",
                   "--inference_ckpt_path", unet_ckpt,
                   "--inference_steps", steps,
                   "--guidance_scale", guidance,
                   "--video_path", ref_mp4,
                   "--audio_path", audio_path,
                   "--video_out_path", out_tmp]
            if os.environ.get("LIPSYNC_DEEPCACHE", "0") == "1":
                cmd.insert(-6, "--enable_deepcache")
            proc = subprocess.run(
                cmd, cwd=_LATENTSYNC_DIR, env=env,
                capture_output=True, text=True,
                timeout=int(os.environ.get("LIPSYNC_TIMEOUT_SECONDS", "10800")))
            if proc.returncode != 0 or not os.path.isfile(out_tmp):
                tail = (proc.stderr or proc.stdout or "")[-1500:]
                raise RuntimeError(f"LatentSync inference failed: {tail}")

            gens_dir = os.path.join(VOICES_DIR, "generations")
            os.makedirs(gens_dir, exist_ok=True)
            out_path = os.path.join(gens_dir, f"{generation_id}.mp4")
            # Re-mux to faststart for browser playback.
            subprocess.run(
                ["ffmpeg", "-y", "-i", out_tmp, "-c", "copy",
                 "-movflags", "+faststart", out_path],
                check=True, capture_output=True)
        _vid(video_status="success", video_path=out_path, video_error=None)
        print(f"[voice] lipsync video ready for generation {generation_id}")
    except Exception as e:
        db.rollback()
        _vid(video_status="error", video_error=str(e)[:500])
        raise
    finally:
        db.close()


def _fit_duration(out_path: str, target_seconds: float):
    """Pitch-preserving time-stretch so the finished audio matches a requested
    total runtime. atempo is clamped to 0.5-2.0x — beyond that speech sounds
    broken anyway."""
    import subprocess
    duration = _probe_duration(out_path)
    if not duration or duration <= 0 or target_seconds <= 0:
        return
    tempo = duration / target_seconds
    tempo = min(2.0, max(0.5, tempo))
    if abs(tempo - 1.0) < 0.02:
        return
    tmp = out_path + ".fit.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-i", out_path, "-filter:a", f"atempo={tempo:.5f}", tmp],
        check=True, capture_output=True,
    )
    os.replace(tmp, out_path)


def _normalize_tts_text(text_value: str) -> str:
    """TTS models are trained on normally-cased text; ALL-CAPS input tokenizes
    into rare tokens and produces garbled audio. Sentence-case shouted text,
    keeping short probable acronyms (TBN, NASA, U.S.) intact.

    Also scrubs the punctuation/spacing artifacts editors paste in: stray
    spaces before punctuation, doubled !/?, and — the big one — single-letter
    name initials ("MICHAEL W. SMITH"): the dot after "W" reads as a sentence
    end, so XTTS's sentence splitter and the Chatterbox chunker both insert a
    hard pause mid-name. Drop that dot (the letter still reads out); dotted
    acronyms like U.S. are left alone."""
    import re as _re

    # Whitespace/punctuation hygiene first — phantom pauses come from here.
    text_value = _re.sub(r"[ \t\u00a0]+", " ", text_value)
    text_value = _re.sub(r" +([,.;:!?…])", r"\1", text_value)
    text_value = _re.sub(r"([!?])\1+", r"\1", text_value)
    # Single-letter initial followed by a capitalized word: "W. Smith" ->
    # "W Smith". Negative lookbehind keeps "U.S." / "L.A." style acronyms.
    text_value = _re.sub(r"(?<![.A-Za-z])([A-Za-z])\.(?= +[A-Z])", r"\1", text_value)

    def fix_word(w: str) -> str:
        core = _re.sub(r"[^A-Za-z]", "", w)
        if core.isupper() and len(core) > 4:
            return w.lower()
        return w

    letters = [c for c in text_value if c.isalpha()]
    mostly_caps = letters and sum(c.isupper() for c in letters) / len(letters) > 0.7
    if mostly_caps:
        # Whole script was pasted in caps — lowercase everything (even short
        # words, they're not acronyms here) then re-capitalize sentence starts.
        out = text_value.lower()
        out = _re.sub(r"(^|[.!?…]\s+|\n\s*)([a-z])",
                      lambda m: m.group(1) + m.group(2).upper(), out)
        out = _re.sub(r"\bi\b", "I", out)
        return out
    # Mixed text: only defuse individual shouted words.
    return " ".join(fix_word(w) for w in text_value.split(" "))


def _split_tts_chunks(text_value: str, max_chars: int = 280) -> list[str]:
    """Split long scripts into sentence-grouped chunks the TTS engine can
    handle. Chatterbox caps generation at ~40s of audio per call and silently
    truncates longer text, so anything long must be synthesized chunk-by-chunk
    and concatenated."""
    import re as _re
    sentences: list[str] = []
    for para in text_value.split("\n"):
        para = para.strip()
        if not para:
            continue
        parts = _re.split(r"(?<=[.!?…])\s+", para)
        sentences.extend(p.strip() for p in parts if p.strip())
    chunks: list[str] = []
    cur = ""
    for s in sentences:
        if cur and len(cur) + 1 + len(s) > max_chars:
            chunks.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
        # A single monster sentence still has to go through on its own.
        while len(cur) > max_chars * 2:
            chunks.append(cur[:max_chars * 2])
            cur = cur[max_chars * 2:].strip()
    if cur:
        chunks.append(cur)
    return chunks or [text_value]


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
        # target_seconds rides in the generation settings but is a
        # post-processing knob, not a synthesis knob — pop it before the
        # settings/preset precedence so a target-only request keeps the
        # person's saved style.
        target_seconds = None
        if gen_settings:
            gen_settings = dict(gen_settings)
            try:
                target_seconds = float(gen_settings.pop("target_seconds", None) or 0) or None
            except (TypeError, ValueError):
                target_seconds = None
            if not gen_settings:
                gen_settings = None
        # Precedence: per-generation settings > per-generation preset (tuning
        # run) > person's saved custom settings > person's saved preset.
        if gen_settings:
            preset, settings = None, gen_settings
        elif gen_preset:
            preset, settings = gen_preset, None
        else:
            preset, settings = person_preset, person_settings

        text_value = _normalize_tts_text(text_value)
        _update_generation(db, generation_id, status="running", progress=5.0)

        speaker_wavs = get_ready_voice_paths(db, person_id)
        if not speaker_wavs:
            raise RuntimeError("No ready voice samples for this person")

        _update_generation(db, generation_id, progress=15.0)

        gens_dir = os.path.join(VOICES_DIR, "generations")
        os.makedirs(gens_dir, exist_ok=True)
        out_path = os.path.join(gens_dir, f"{generation_id}.wav")

        # Merge preset + custom sliders once so both engines see the same knobs.
        merged = dict(PRESET_SETTINGS.get(preset or "natural", {}))
        if settings:
            merged.update({k: v for k, v in settings.items()
                           if k in _ALLOWED_SETTINGS and v is not None})
        merged = _sanitize_settings(merged)

        started = time.monotonic()
        # Engine dispatch. Per-generation/person "engine" setting wins, then
        # VOICE_ENGINE env, then automatic: English -> Chatterbox-Turbo,
        # anything else -> multilingual Chatterbox, XTTS as the last resort.
        # DUB_ENGINE=xtts still forces the legacy engine globally.
        engine = str(merged.pop("engine", "") or os.environ.get("VOICE_ENGINE", "")).lower()
        if os.environ.get("DUB_ENGINE", "").lower() == "xtts":
            engine = "xtts"
        used_chatterbox = False

        if engine == "qwen3":
            try:
                from tasks.dub import _write_wav
                model = _load_qwen3_tts()
                _update_generation(db, generation_id, progress=30.0)
                ref = speaker_wavs[0]
                ref_text = _ref_transcript(ref)
                wavs, sr = model.generate_voice_clone(
                    text=text_value,
                    language=_QWEN3_LANGS.get(str(language).lower(), "English"),
                    ref_audio=ref,
                    ref_text=ref_text,
                    x_vector_only_mode=ref_text is None,
                )
                _write_wav(out_path, wavs[0], sr)
                speed = merged.get("speed")
                if speed and abs(float(speed) - 1.0) > 1e-3:
                    _ffmpeg_atempo(out_path, float(speed))
                used_chatterbox = True  # skip the fallback engines below
                print(f"[voice] generated with qwen3-tts for generation {generation_id}")
            except Exception as e:
                print(f"[voice] qwen3-tts failed, falling back: {e}")

        if (not used_chatterbox and engine in ("", "turbo")
                and str(language).lower().startswith("en")):
            import tempfile
            try:
                import numpy as np
                from tasks.dub import _write_wav
                model = _load_chatterbox_turbo()
                _update_generation(db, generation_id, progress=30.0)
                chunks = _split_tts_chunks(text_value)
                pieces, rate = [], None
                for ci, chunk in enumerate(chunks):
                    wav = model.generate(chunk, audio_prompt_path=speaker_wavs[0])
                    pieces.append(wav.squeeze(0).detach().cpu().numpy())
                    rate = model.sr
                    _update_generation(
                        db, generation_id,
                        progress=30.0 + 60.0 * (ci + 1) / len(chunks))
                if len(pieces) == 1:
                    samples = pieces[0]
                else:
                    gap = np.zeros(int(rate * 0.25), dtype=pieces[0].dtype)
                    joined = []
                    for pi, p in enumerate(pieces):
                        if pi:
                            joined.append(gap)
                        joined.append(p)
                    samples = np.concatenate(joined)
                _write_wav(out_path, samples, rate)
                speed = merged.get("speed")
                if speed and abs(float(speed) - 1.0) > 1e-3:
                    _ffmpeg_atempo(out_path, float(speed))
                used_chatterbox = True
                print(f"[voice] generated with chatterbox-turbo for generation {generation_id}")
            except Exception as e:
                print(f"[voice] chatterbox-turbo failed, falling back: {e}")

        if not used_chatterbox and engine != "xtts":
            import tempfile
            from tasks.dub import _load_chatterbox, _synthesize_chatterbox, _to_chatterbox_lang, _write_wav
            cb_lang = _to_chatterbox_lang(language)
            if cb_lang:
                try:
                    import numpy as np
                    model = _load_chatterbox()
                    _update_generation(db, generation_id, progress=30.0)
                    chunks = _split_tts_chunks(text_value)
                    pieces = []
                    with tempfile.TemporaryDirectory() as workdir:
                        rate = None
                        for ci, chunk in enumerate(chunks):
                            samples, rate = _synthesize_chatterbox(
                                model, chunk, cb_lang, speaker_wavs[0], workdir, merged)
                            pieces.append(samples)
                            _update_generation(
                                db, generation_id,
                                progress=30.0 + 60.0 * (ci + 1) / len(chunks))
                    if len(pieces) == 1:
                        samples = pieces[0]
                    else:
                        # Short pause between chunks so sentence boundaries breathe.
                        gap = np.zeros(int(rate * 0.25), dtype=pieces[0].dtype)
                        joined = []
                        for pi, p in enumerate(pieces):
                            if pi:
                                joined.append(gap)
                            joined.append(p)
                        samples = np.concatenate(joined)
                    _write_wav(out_path, samples, rate)
                    used_chatterbox = True
                    print(f"[voice] generated with chatterbox for generation {generation_id}")
                except Exception as e:
                    print(f"[voice] chatterbox failed, falling back to XTTS: {e}")
        if not used_chatterbox:
            tts = _load_xtts()
            _update_generation(db, generation_id, progress=40.0)
            # Longest 1-2 clean references beat a pile of mixed recordings.
            synthesize_cloned(tts, text_value, language, speaker_wavs[:2], out_path,
                              preset=preset, settings=settings)
        if target_seconds:
            _fit_duration(out_path, target_seconds)
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
