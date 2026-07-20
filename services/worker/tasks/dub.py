"""Dubbed audio track generation from translated transcripts via Meta MMS-TTS."""
import json
import math
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
# Cap fit-to-slot speed-up at a barely noticeable rate. Anything above ~1.35x
# sounds like chipmunk speech; overlong clips instead spill into the following
# silence (the placement cursor below prevents overlap with the next segment).
_MAX_ATEMPO = 1.35
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

# Chatterbox multilingual (ResembleAI) — preferred cloned-voice engine; more
# natural than XTTS-v2. Set DUB_ENGINE=xtts to force the old path.
CHATTERBOX_LANGS = {
    "ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi", "it", "ja",
    "ko", "ms", "nl", "no", "pl", "pt", "ru", "sv", "sw", "tr", "zh",
}
_chatterbox_cache: dict = {}


def _to_chatterbox_lang(target: str) -> str | None:
    lang = "zh" if target == "zh-cn" else target
    return lang if lang in CHATTERBOX_LANGS else None


def _load_chatterbox():
    """Load Chatterbox multilingual once per worker process (GPU-resident)."""
    if "model" in _chatterbox_cache:
        return _chatterbox_cache["model"]
    import torch
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = ChatterboxMultilingualTTS.from_pretrained(device=device)
    # transformers>=4.48 defaults attention to sdpa, but Chatterbox's
    # generation requests output_attentions (alignment stream analyzer),
    # which sdpa rejects: "The `output_attentions` attribute is not
    # supported ... set it to 'eager' instead." Force eager attention on
    # every HF submodule config.
    _force_eager_attention(model)
    _chatterbox_cache["model"] = model
    return model


def _force_eager_attention(model):
    """Set attn_implementation='eager' on all HF configs inside a Chatterbox model."""
    seen = set()

    def _patch(cfg):
        if cfg is None or id(cfg) in seen:
            return
        seen.add(id(cfg))
        try:
            cfg._attn_implementation = "eager"
            if hasattr(cfg, "attn_implementation"):
                cfg.attn_implementation = "eager"
        except Exception:
            pass

    for attr in ("t3", "s3gen", "ve"):
        sub = getattr(model, attr, None)
        if sub is None:
            continue
        _patch(getattr(sub, "config", None))
        tfmr = getattr(sub, "tfmr", None)
        if tfmr is not None:
            _patch(getattr(tfmr, "config", None))
            gen_cfg = getattr(tfmr, "generation_config", None)
            _patch(gen_cfg)
        try:
            import torch.nn as nn
            if isinstance(sub, nn.Module):
                for m in sub.modules():
                    _patch(getattr(m, "config", None))
        except Exception:
            pass


def _synthesize_chatterbox(model, text_value: str, lang_id: str, ref_wav: str,
                           workdir: str, settings: dict | None):
    """Cloned-voice synthesis via Chatterbox. Maps our voice settings where the
    engine has an equivalent: temperature directly, speed via pitch-preserving
    atempo. top_p / repetition_penalty are XTTS-specific and ignored here."""
    kwargs = {}
    if settings and settings.get("temperature") is not None:
        temp = float(settings["temperature"])
        if math.isfinite(temp) and 0 < temp <= 1.5:
            kwargs["temperature"] = temp
    wav = model.generate(text_value, language_id=lang_id, audio_prompt_path=ref_wav, **kwargs)
    samples = wav.squeeze(0).float().cpu().numpy()
    rate = int(model.sr)
    speed = float(settings.get("speed") or 1.0) if settings else 1.0
    if not math.isfinite(speed) or speed <= 0:
        speed = 1.0
    speed = min(2.0, max(0.5, speed))
    if abs(speed - 1.0) >= 0.01:
        samples = _atempo(samples, rate, speed, workdir)
    return samples, rate

# XTTS-v2 built-in studio speakers used for gender-matched generic dubbing
# (no cloned voice profile needed).
STOCK_VOICES = {"female": "Claribel Dervla", "male": "Damien Black"}
# Median F0 at/above this → female. Typical male speech 85-155 Hz,
# female 165-255 Hz.
_F0_FEMALE_HZ = 155.0


def _median_f0(samples, rate: int) -> float | None:
    """Median fundamental frequency of voiced frames via autocorrelation."""
    import numpy as np
    frame = int(rate * 0.04)
    hop = frame // 2
    lo_lag = int(rate / 400.0)   # 400 Hz ceiling
    hi_lag = int(rate / 60.0)    # 60 Hz floor
    if samples.size < frame or hi_lag <= lo_lag:
        return None
    energy_gate = 0.05 * float(np.sqrt(np.mean(samples ** 2)) or 0.0)
    f0s = []
    for start in range(0, samples.size - frame, hop):
        w = samples[start:start + frame]
        rms = float(np.sqrt(np.mean(w ** 2)))
        if rms < max(energy_gate, 1e-4):
            continue
        w = w - w.mean()
        ac = np.correlate(w, w, mode="full")[frame - 1:]
        if ac[0] <= 0:
            continue
        seg = ac[lo_lag:hi_lag]
        if seg.size == 0:
            continue
        lag = lo_lag + int(np.argmax(seg))
        # Voicing confidence: normalized autocorrelation peak
        if ac[lag] / ac[0] < 0.3:
            continue
        f0s.append(rate / lag)
    if len(f0s) < 10:
        return None
    return float(np.median(np.array(f0s)))


def _speaker_genders(db, media_id: str, workdir: str) -> dict:
    """speaker_label → 'male' | 'female', estimated from source audio pitch.
    Defaults to 'male' when estimation fails (no audio, too little speech)."""
    from sqlalchemy import text
    row = db.execute(
        text("SELECT original_path, proxy_path FROM media_assets WHERE id = :mid"),
        {"mid": media_id},
    ).fetchone()
    src = (row[1] or row[0]) if row else None
    genders: dict = {}
    if not src or not os.path.exists(src):
        return genders
    segs = db.execute(
        text("""
            SELECT DISTINCT ON (speaker, start_time) speaker, start_time, end_time
            FROM transcript_segments
            WHERE media_id = :mid AND speaker IS NOT NULL
              AND end_time - start_time >= 2.0
            ORDER BY speaker, start_time
        """),
        {"mid": media_id},
    ).fetchall()
    by_speaker: dict = {}
    for spk, s, e in segs:
        by_speaker.setdefault(spk, [])
        if len(by_speaker[spk]) < 3:
            by_speaker[spk].append((float(s), float(e)))
    for spk, windows in by_speaker.items():
        f0s = []
        for s, e in windows:
            wav = os.path.join(workdir, "gender_probe.wav")
            proc = subprocess.run(
                ["ffmpeg", "-y", "-ss", str(s), "-to", str(min(e, s + 8.0)),
                 "-i", src, "-vn", "-ac", "1", "-ar", "16000", wav],
                capture_output=True, timeout=120,
            )
            if proc.returncode != 0 or not os.path.exists(wav):
                continue
            try:
                data, rate = _read_wav(wav)
                f0 = _median_f0(data, rate)
                if f0:
                    f0s.append(f0)
            except Exception:
                continue
        if f0s:
            import numpy as np
            med = float(np.median(np.array(f0s)))
            genders[spk] = "female" if med >= _F0_FEMALE_HZ else "male"
    return genders


def _synthesize_stock(tts, text_value: str, language: str, speaker_name: str, workdir: str):
    out = os.path.join(workdir, "xtts_stock_seg.wav")
    tts.tts_to_file(text=text_value, language=language, speaker=speaker_name, file_path=out)
    return _read_wav(out)


def _cloned_voice_map(db, media_id: str) -> tuple[dict, list[str]]:
    """speaker_label → (ready voice-sample WAV paths, saved preset, saved settings).

    Also returns human-readable notes explaining every speaker/person that did
    NOT get a cloned voice, so 'why is it using a stock voice' is answerable
    from the job log.
    """
    from sqlalchemy import text
    from tasks.voice import get_ready_voice_paths, MIN_SAMPLE_SECONDS
    rows = db.execute(
        text("""
            SELECT pa.speaker_label, pa.person_id, p.display_name,
                   p.voice_preset, p.voice_settings
            FROM person_appearances pa JOIN people p ON p.id = pa.person_id
            WHERE pa.media_id = :mid
        """),
        {"mid": media_id},
    ).fetchall()
    result = {}
    notes = []
    for speaker_label, person_id, display_name, voice_preset, voice_settings in rows:
        if speaker_label is None:
            notes.append(f"{display_name}: linked by face only (no speaker label on this asset) — cannot map to dialogue")
            continue
        paths = get_ready_voice_paths(db, person_id)
        if paths:
            result[speaker_label] = (paths[:2], voice_preset, voice_settings)
            continue
        # Diagnose why there are no usable samples.
        srows = db.execute(
            text("""
                SELECT status, audio_path, COALESCE(duration_seconds, 0)
                FROM voice_samples WHERE person_id = :pid
            """),
            {"pid": person_id},
        ).fetchall()
        if not srows:
            notes.append(f"{display_name} ({speaker_label}): no voice samples")
            continue
        ready = [(p, d) for s, p, d in srows if s == "ready" and p]
        missing = [p for p, _ in ready if not os.path.isfile(p)]
        total = sum(d for p, d in ready if os.path.isfile(p))
        if not ready:
            statuses = ", ".join(sorted({s for s, _, _ in srows}))
            notes.append(f"{display_name} ({speaker_label}): {len(srows)} sample(s) but none ready (status: {statuses})")
        elif missing:
            notes.append(f"{display_name} ({speaker_label}): {len(missing)} ready sample file(s) missing on disk")
        else:
            notes.append(
                f"{display_name} ({speaker_label}): ready samples total {total:.0f}s "
                f"— need at least {MIN_SAMPLE_SECONDS:.0f}s"
            )
    return result, notes


def _synthesize_xtts(tts, text_value: str, language: str, speaker_wavs, workdir: str,
                     preset=None, settings=None):
    from tasks.voice import synthesize_cloned
    out = os.path.join(workdir, "xtts_seg.wav")
    synthesize_cloned(tts, text_value, language, speaker_wavs, out, preset=preset, settings=settings)
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
        if not lang3 and target not in XTTS_LANGS:
            supported = sorted(set(MMS_LANG_CODES) | XTTS_LANGS)
            raise RuntimeError(
                f"Dubbing not supported for '{target}'. Supported: {', '.join(supported)}"
            )

        update_job(db, job_id, status="running", started_at=datetime.utcnow(),
                   celery_task_id=self.request.id, progress=0.0)

        from sqlalchemy import text
        asset_row = db.execute(
            text("SELECT duration_seconds, original_path, proxy_path FROM media_assets WHERE id = :mid"),
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
        # Drop rows with non-finite timecodes (bad probe/transcribe data can
        # leave Infinity/NaN in the DB, which crashes int() conversions below).
        dropped = [r for r in rows if not (math.isfinite(float(r[0])) and math.isfinite(float(r[1])))]
        if dropped:
            append_log(db, job_id, f"Skipping {len(dropped)} segment(s) with invalid timecodes")
            rows = [r for r in rows if r not in dropped]
        if not rows:
            raise RuntimeError(
                f"No '{target}' translation found — run translation first"
            )

        # Cloned-voice path: map diarized speakers to ready voice profiles.
        voice_map: dict = {}
        xtts = None
        chatterbox = None
        chatterbox_lang = _to_chatterbox_lang(target)
        if use_cloned_voices and target in XTTS_LANGS:
            voice_map, voice_notes = _cloned_voice_map(db, media_id)
            if voice_map:
                append_log(db, job_id, f"{len(voice_map)} speaker(s) have ready cloned-voice profiles")
            else:
                append_log(db, job_id, "Cloned voices requested but no speaker has a ready voice profile — using stock voices")
            for note in voice_notes:
                append_log(db, job_id, f"No cloned voice — {note}")
                print(f"[dub] no cloned voice — {note}")
        elif use_cloned_voices:
            append_log(db, job_id, f"Cloned voices not supported for '{target}' — using stock voices")

        # Preferred cloned-voice engine: Chatterbox multilingual. Any load
        # failure (missing package, download issue) falls back to XTTS.
        if voice_map and chatterbox_lang and os.getenv("DUB_ENGINE", "chatterbox") != "xtts":
            try:
                append_log(db, job_id, "Loading Chatterbox multilingual (cloned voices)")
                update_job(db, job_id, progress=2.0)
                chatterbox = _load_chatterbox()
                print("[dub] chatterbox loaded — cloned segments will use chatterbox")
            except Exception as e:
                print(f"[dub] chatterbox unavailable, cloned voices will use XTTS: {e}")
                append_log(db, job_id, f"Chatterbox unavailable ({e}) — cloned voices will use XTTS-v2")

        # Generic (non-cloned) segments: prefer XTTS stock studio voices,
        # gender-matched to each diarized speaker's pitch. MMS-TTS (one
        # androgynous voice per language) is only the fallback for languages
        # XTTS can't speak.
        speaker_genders: dict = {}
        use_xtts_stock = target in XTTS_LANGS
        if use_xtts_stock or voice_map:
            append_log(db, job_id, "Loading XTTS-v2")
            update_job(db, job_id, progress=3.0)
            from tasks.voice import _load_xtts
            xtts = _load_xtts()

        tokenizer = model = None
        if xtts:
            sample_rate = 24000  # XTTS output rate
        else:
            if not lang3:
                raise RuntimeError(f"No MMS-TTS checkpoint for '{target}'")
            append_log(db, job_id, f"Loading TTS model: facebook/mms-tts-{lang3}")
            update_job(db, job_id, progress=5.0)
            tokenizer, model, sample_rate = _load_tts(lang3)

        asset_duration = float(asset_row[0]) if asset_row[0] else 0.0
        if not math.isfinite(asset_duration) or asset_duration <= 0:
            asset_duration = float(rows[-1][1]) + 1.0
        duration = max(asset_duration, float(rows[-1][1]))
        timeline = np.zeros(int(duration * sample_rate) + sample_rate, dtype=np.float32)

        append_log(db, job_id, f"Synthesizing {len(rows)} segments ({target})")
        total = len(rows)
        last_report = time.monotonic()
        synthesized = 0
        place_cursor = 0

        cloned_count = 0
        chatterbox_count = 0
        with tempfile.TemporaryDirectory() as workdir:
            if use_xtts_stock:
                speaker_genders = _speaker_genders(db, media_id, workdir)
                if speaker_genders:
                    summary = ", ".join(f"{s}: {g}" for s, g in sorted(speaker_genders.items()))
                    append_log(db, job_id, f"Gender-matched stock voices — {summary}")

            for i, (start_time, end_time, seg_text, speaker) in enumerate(rows):
                seg_text = (seg_text or "").strip()
                if not seg_text:
                    continue
                cloned = voice_map.get(speaker) if (xtts or chatterbox) else None
                try:
                    if cloned:
                        speaker_wavs, voice_preset, voice_settings = cloned
                        clip = None
                        if chatterbox is not None:
                            try:
                                clip, clip_rate = _synthesize_chatterbox(
                                    chatterbox, seg_text, chatterbox_lang,
                                    speaker_wavs[0], workdir, voice_settings,
                                )
                                chatterbox_count += 1
                            except Exception as e:
                                append_log(db, job_id, f"Chatterbox failed on segment {i + 1} ({e}) — XTTS fallback")
                        if clip is None:
                            clip, clip_rate = _synthesize_xtts(
                                xtts, seg_text, target, speaker_wavs, workdir,
                                preset=voice_preset, settings=voice_settings,
                            )
                        clip = _resample(clip, clip_rate, sample_rate, workdir)
                        cloned_count += 1
                    elif use_xtts_stock:
                        gender = speaker_genders.get(speaker, "male")
                        clip, clip_rate = _synthesize_stock(
                            xtts, seg_text, target, STOCK_VOICES[gender], workdir
                        )
                        clip = _resample(clip, clip_rate, sample_rate, workdir)
                    else:
                        if model is None:
                            append_log(db, job_id, f"Loading TTS model: facebook/mms-tts-{lang3}")
                            tokenizer, model, mms_rate = _load_tts(lang3)
                        clip = _synthesize(tokenizer, model, seg_text)
                        if clip is not None and clip.size:
                            clip = _resample(clip, int(model.config.sampling_rate), sample_rate, workdir)
                except Exception as e:
                    import traceback
                    tb_line = traceback.format_exc().strip().splitlines()[-3:]
                    append_log(db, job_id, f"Segment {i + 1}/{total} failed, skipping: {e} | {' / '.join(tb_line)}")
                    continue
                if clip is None or clip.size == 0:
                    continue

                start = float(start_time)
                next_start = float(rows[i + 1][0]) if i + 1 < total else duration
                if not math.isfinite(next_start):
                    next_start = duration
                slot = max(0.5, next_start - start)
                clip_len = clip.size / sample_rate
                if clip_len > slot * 1.05:
                    factor = min(_MAX_ATEMPO, clip_len / slot)
                    if factor > 1.02:
                        clip = _atempo(clip, sample_rate, factor, workdir)

                # Never overlap the previous clip: if it ran past this
                # segment's start, begin right after it instead. Translated
                # speech runs longer than the original, so bounded drift
                # sounds far better than double-talk or 2x chipmunk speed.
                offset = max(int(start * sample_rate), place_cursor)
                end = min(offset + clip.size, timeline.size)
                if offset < timeline.size:
                    timeline[offset:end] += clip[: end - offset]
                    place_cursor = end
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

            # Mux a playable dubbed VIDEO: copy the video stream (no re-encode)
            # and attach the dubbed track, so the player can switch sources
            # instead of syncing a separate audio element.
            # The player switches its source to this MP4, so a missing mux
            # must FAIL the job — otherwise the language is advertised as
            # dubbed and playback 404s.
            video_src = asset_row[2] or asset_row[1]
            if not video_src or not os.path.exists(video_src):
                raise RuntimeError("Source video unavailable — cannot produce dubbed video")
            append_log(db, job_id, "Muxing dubbed video")
            update_job(db, job_id, progress=96.0)
            tmp_mp4 = os.path.join(workdir, "dub_video.mp4")
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", video_src, "-i", tmp_out,
                 "-map", "0:v:0", "-map", "1:a:0",
                 "-c:v", "copy", "-c:a", "copy",
                 "-movflags", "+faststart", "-shortest", tmp_mp4],
                capture_output=True, text=True, timeout=1800,
            )
            if result.returncode != 0 or not os.path.exists(tmp_mp4):
                raise RuntimeError(f"Dubbed video mux failed: {result.stderr[-300:]}")
            shutil.copyfile(tmp_mp4, os.path.join(DUBS_DIR, f"{media_id}_{target}.mp4"))

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
        cloned_note = (
            f" ({cloned_count} in cloned voices — {chatterbox_count} chatterbox, "
            f"{cloned_count - chatterbox_count} XTTS)"
        ) if cloned_count else ""
        print(f"[dub] {target}: {synthesized}/{total} segments — "
              f"{chatterbox_count} chatterbox, {cloned_count - chatterbox_count} cloned-XTTS, "
              f"{synthesized - cloned_count} stock/MMS")
        append_log(db, job_id, f"Dubbed {synthesized}/{total} segments to '{target}'{cloned_note} → {os.path.basename(out_path)}")

    except Exception as e:
        import traceback
        db.rollback()
        tb_tail = " / ".join(traceback.format_exc().strip().splitlines()[-3:])
        append_log(db, job_id, f"Traceback: {tb_tail}")
        update_job(db, job_id, status="error", error_message=str(e), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()
