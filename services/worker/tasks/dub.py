"""Dubbed audio track generation from translated transcripts via Meta MMS-TTS."""
import json
import os
import subprocess
import tempfile
import time
import wave
from datetime import datetime

from app import celery_app
from db import get_session
from tasks.base import update_job, append_log
from config import DUBS_DIR

# ISO code → MMS-TTS ISO 639-3 model suffix. Only languages with a published
# facebook/mms-tts-* checkpoint (no Italian, Japanese, or Chinese models exist).
MMS_LANG_CODES = {
    "es": "spa",
    "fr": "fra",
    "de": "deu",
    "pt": "por",
    "nl": "nld",
    "ru": "rus",
    "ko": "kor",
    "ar": "ara",
    "hi": "hin",
}

# Max speed-up applied to a synthesized clip so it fits its transcript slot.
_MAX_ATEMPO = 2.0
# Loaded (tokenizer, model, sample_rate) per language, one at a time.
_tts_cache: dict = {}


def _load_tts(lang3: str):
    if lang3 in _tts_cache:
        return _tts_cache[lang3]
    import torch
    from huggingface_hub import snapshot_download
    from transformers import AutoTokenizer, VitsModel

    # snapshot_download first, then load from the local path — loading a hub repo
    # id directly can spawn a safetensors-conversion subprocess, which Celery's
    # daemonized prefork workers cannot do.
    local_dir = snapshot_download(f"facebook/mms-tts-{lang3}")
    tokenizer = AutoTokenizer.from_pretrained(local_dir)
    model = VitsModel.from_pretrained(local_dir)
    if torch.cuda.is_available():
        model = model.to("cuda")
    model.eval()
    _tts_cache.clear()  # keep at most one language resident
    _tts_cache[lang3] = (tokenizer, model, int(model.config.sampling_rate))
    return _tts_cache[lang3]


def _romanize_if_needed(tokenizer, text: str) -> str:
    """MMS checkpoints for some scripts were trained on uroman-romanized text."""
    if not getattr(tokenizer, "is_uroman", False):
        return text
    try:
        import uroman as ur
        if not hasattr(_romanize_if_needed, "_uroman"):
            _romanize_if_needed._uroman = ur.Uroman()
        return _romanize_if_needed._uroman.romanize_string(text)
    except ImportError:
        raise RuntimeError(
            "This MMS-TTS checkpoint requires uroman romanization — "
            "add the 'uroman' package to the worker image"
        )


def _synthesize(tokenizer, model, text: str):
    import torch
    inputs = tokenizer(_romanize_if_needed(tokenizer, text), return_tensors="pt").to(model.device)
    if inputs["input_ids"].shape[-1] == 0:
        return None
    with torch.no_grad():
        output = model(**inputs)
    return output.waveform[0].float().cpu().numpy()


def _write_wav(path: str, samples, sample_rate: int):
    import numpy as np
    clipped = np.clip(samples, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())


def _read_wav(path: str):
    import numpy as np
    with wave.open(path, "rb") as wf:
        frames = wf.readframes(wf.getnframes())
        data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32767.0
        if wf.getnchannels() > 1:
            data = data.reshape(-1, wf.getnchannels()).mean(axis=1)
        return data, wf.getframerate()


def _resample(samples, from_rate: int, to_rate: int, workdir: str):
    if from_rate == to_rate:
        return samples
    src = os.path.join(workdir, "resample_in.wav")
    dst = os.path.join(workdir, "resample_out.wav")
    _write_wav(src, samples, from_rate)
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-ar", str(to_rate), dst],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg resample failed: {result.stderr[-400:]}")
    data, _ = _read_wav(dst)
    return data


# XTTS-v2 supported languages (voice cloning path).
XTTS_LANGS = {
    "en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru",
    "nl", "cs", "ar", "zh-cn", "ja", "hu", "ko", "hi",
}


def _cloned_voice_map(db, media_id: str) -> dict:
    """speaker_label → list of ready voice-sample WAV paths for this asset's people."""
    from sqlalchemy import text
    from tasks.voice import get_ready_voice_paths
    rows = db.execute(
        text("""
            SELECT speaker_label, person_id FROM person_appearances
            WHERE media_id = :mid AND speaker_label IS NOT NULL
        """),
        {"mid": media_id},
    ).fetchall()
    result = {}
    for speaker_label, person_id in rows:
        paths = get_ready_voice_paths(db, person_id)
        if paths:
            result[speaker_label] = paths[:3]
    return result


def _synthesize_xtts(tts, text_value: str, language: str, speaker_wavs, workdir: str):
    from tasks.voice import synthesize_cloned
    out = os.path.join(workdir, "xtts_seg.wav")
    synthesize_cloned(tts, text_value, language, speaker_wavs, out)
    return _read_wav(out)


def _atempo(samples, sample_rate: int, factor: float, workdir: str):
    """Pitch-preserving speed-up via ffmpeg atempo (chained for factors > 2)."""
    src = os.path.join(workdir, "atempo_in.wav")
    dst = os.path.join(workdir, "atempo_out.wav")
    _write_wav(src, samples, sample_rate)
    filters = []
    remaining = factor
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    filters.append(f"atempo={remaining:.4f}")
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-filter:a", ",".join(filters), dst],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg atempo failed: {result.stderr[-400:]}")
    data, _ = _read_wav(dst)
    return data


@celery_app.task(bind=True, name="tasks.dub.generate_dub", queue="gpu")
def generate_dub(self, media_id: str, job_id: str, target_language: str, use_cloned_voices: bool = False):
    db = get_session()
    try:
        import numpy as np

        target = str(target_language).strip().lower()
        lang3 = MMS_LANG_CODES.get(target)
        if not lang3:
            raise RuntimeError(
                f"Dubbing not supported for '{target}'. Supported: {', '.join(sorted(MMS_LANG_CODES))}"
            )

        update_job(db, job_id, status="running", started_at=datetime.utcnow(),
                   celery_task_id=self.request.id, progress=0.0)

        from sqlalchemy import text
        asset_row = db.execute(
            text("SELECT duration_seconds FROM media_assets WHERE id = :mid"),
            {"mid": media_id},
        ).fetchone()
        if not asset_row:
            raise RuntimeError("Media asset not found")

        rows = db.execute(
            text("""
                SELECT start_time, end_time, translations ->> :lang, speaker
                FROM transcript_segments
                WHERE media_id = :mid AND translations ->> :lang IS NOT NULL
                ORDER BY start_time
            """),
            {"mid": media_id, "lang": target},
        ).fetchall()
        if not rows:
            raise RuntimeError(
                f"No '{target}' translation found — run translation first"
            )

        # Cloned-voice path: map diarized speakers to ready voice profiles.
        voice_map: dict = {}
        xtts = None
        if use_cloned_voices and target in XTTS_LANGS:
            voice_map = _cloned_voice_map(db, media_id)
            if voice_map:
                append_log(db, job_id, f"Loading XTTS-v2 for cloned voices ({len(voice_map)} speaker(s) with ready profiles)")
                from tasks.voice import _load_xtts
                xtts = _load_xtts()
            else:
                append_log(db, job_id, "Cloned voices requested but no speaker has a ready voice profile — using stock TTS")
        elif use_cloned_voices:
            append_log(db, job_id, f"Cloned voices not supported for '{target}' — using stock TTS")

        needs_mms = any(not (xtts and voice_map.get(r[3])) for r in rows)
        tokenizer = model = None
        if needs_mms:
            append_log(db, job_id, f"Loading TTS model: facebook/mms-tts-{lang3}")
            update_job(db, job_id, progress=5.0)
            tokenizer, model, sample_rate = _load_tts(lang3)
        else:
            sample_rate = 24000  # XTTS output rate
        if xtts:
            sample_rate = 24000

        duration = float(asset_row[0]) if asset_row[0] else float(rows[-1][1]) + 1.0
        duration = max(duration, float(rows[-1][1]))
        timeline = np.zeros(int(duration * sample_rate) + sample_rate, dtype=np.float32)

        append_log(db, job_id, f"Synthesizing {len(rows)} segments ({target})")
        total = len(rows)
        last_report = time.monotonic()
        synthesized = 0

        cloned_count = 0
        with tempfile.TemporaryDirectory() as workdir:
            for i, (start_time, end_time, seg_text, speaker) in enumerate(rows):
                seg_text = (seg_text or "").strip()
                if not seg_text:
                    continue
                speaker_wavs = voice_map.get(speaker) if xtts else None
                if speaker_wavs:
                    clip, clip_rate = _synthesize_xtts(xtts, seg_text, target, speaker_wavs, workdir)
                    clip = _resample(clip, clip_rate, sample_rate, workdir)
                    cloned_count += 1
                else:
                    if model is None:
                        append_log(db, job_id, f"Loading TTS model: facebook/mms-tts-{lang3}")
                        tokenizer, model, mms_rate = _load_tts(lang3)
                    clip = _synthesize(tokenizer, model, seg_text)
                    if clip is not None and clip.size:
                        clip = _resample(clip, int(model.config.sampling_rate), sample_rate, workdir)
                if clip is None or clip.size == 0:
                    continue

                start = float(start_time)
                next_start = float(rows[i + 1][0]) if i + 1 < total else duration
                slot = max(0.5, next_start - start)
                clip_len = clip.size / sample_rate
                if clip_len > slot * 1.05:
                    factor = min(_MAX_ATEMPO, clip_len / slot)
                    clip = _atempo(clip, sample_rate, factor, workdir)

                offset = int(start * sample_rate)
                end = min(offset + clip.size, timeline.size)
                if offset < timeline.size:
                    timeline[offset:end] += clip[: end - offset]
                synthesized += 1

                now = time.monotonic()
                if now - last_report >= 3 or i + 1 == total:
                    update_job(db, job_id, progress=round(5.0 + 85.0 * (i + 1) / total, 1))
                    last_report = now

            if synthesized == 0:
                raise RuntimeError("No segments could be synthesized")

            peak = float(np.max(np.abs(timeline)))
            if peak > 0.95:
                timeline *= 0.95 / peak

            append_log(db, job_id, "Encoding dubbed track to M4A")
            update_job(db, job_id, progress=92.0)
            mix_wav = os.path.join(workdir, "dub_mix.wav")
            _write_wav(mix_wav, timeline, sample_rate)

            os.makedirs(DUBS_DIR, exist_ok=True)
            out_path = os.path.join(DUBS_DIR, f"{media_id}_{target}.m4a")
            tmp_out = os.path.join(workdir, "dub_out.m4a")
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", mix_wav, "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", tmp_out],
                capture_output=True, text=True, timeout=600,
            )
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg AAC encode failed: {result.stderr[-400:]}")
            import shutil
            shutil.copyfile(tmp_out, out_path)

        db.execute(
            text("""
                UPDATE media_assets
                SET dubbed_languages = (
                    SELECT jsonb_agg(DISTINCT lang)
                    FROM jsonb_array_elements_text(
                        COALESCE(dubbed_languages, '[]'::jsonb) || CAST(:lang AS jsonb)
                    ) AS lang
                )
                WHERE id = :mid
            """),
            {"lang": json.dumps([target]), "mid": media_id},
        )
        db.commit()

        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
        cloned_note = f" ({cloned_count} in cloned voices)" if cloned_count else ""
        append_log(db, job_id, f"Dubbed {synthesized}/{total} segments to '{target}'{cloned_note} → {os.path.basename(out_path)}")

    except Exception as e:
        db.rollback()
        update_job(db, job_id, status="error", error_message=str(e), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()
