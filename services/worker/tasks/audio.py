"""Extract audio track as WAV for transcription."""
import os
import subprocess
from datetime import datetime
from app import celery_app
from db import get_session
from tasks.base import update_job, append_log, update_asset
from config import AUDIO_DIR


@celery_app.task(bind=True, name="tasks.audio.extract_audio", queue="cpu")
def extract_audio(self, media_id: str, job_id: str):
    db = get_session()
    try:
        update_job(db, job_id, status="running", started_at=datetime.utcnow(), celery_task_id=self.request.id)
        update_asset(db, media_id, processing_stage="audio_extract", processing_progress=30.0)

        from sqlalchemy import text
        row = db.execute(text("SELECT original_path FROM media_assets WHERE id = :mid"), {"mid": media_id}).fetchone()
        src = row[0]

        os.makedirs(AUDIO_DIR, exist_ok=True)
        audio_path = os.path.join(AUDIO_DIR, f"{media_id}.wav")
        append_log(db, job_id, f"Extracting audio to {audio_path}")

        # Curator WebProxy _video.mp4 files are video-only: the audio lives in
        # sidecar _audioN.mp4 files in the same folder. Extract from those.
        from tasks.curator import is_curator_video, has_audio_stream, find_curator_audio
        inputs = [src]
        if is_curator_video(src) and not has_audio_stream(src):
            sidecars = find_curator_audio(src)
            if not sidecars:
                raise RuntimeError(
                    "Source video has no audio track and no Curator _audioN.mp4 "
                    "sidecar was found next to it"
                )
            inputs = sidecars
            append_log(db, job_id, "Video-only Curator proxy — using sidecar audio: "
                       + ", ".join(os.path.basename(p) for p in inputs))

        # Mix EVERY audio stream of every input. Camera/dailies files (.mov
        # especially) carry several mono tracks (boom, lav, spares) — ffmpeg's
        # default selection takes only ONE, often a silent channel, so Whisper
        # would transcribe silence.
        def _count_audio_streams(path: str) -> int:
            try:
                import json as _json
                out = subprocess.run(
                    ["ffprobe", "-v", "error", "-select_streams", "a",
                     "-show_entries", "stream=index", "-of", "json", path],
                    capture_output=True, text=True, timeout=30,
                )
                return len(_json.loads(out.stdout or "{}").get("streams") or [])
            except Exception:
                return 1

        cmd = ["ffmpeg", "-y"]
        pads = []
        for i, p in enumerate(inputs):
            cmd += ["-i", p]
            n = max(1, _count_audio_streams(p))
            pads += [f"[{i}:a:{j}]" for j in range(n)]
        if len(pads) > 1:
            cmd += ["-filter_complex",
                    f"{''.join(pads)}amix=inputs={len(pads)}:duration=longest:normalize=0"]
            append_log(db, job_id, f"Mixing {len(pads)} audio streams")
        cmd += [
            "-vn", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1",
            audio_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg audio extract failed: {result.stderr[-500:]}")

        # Guard against phase cancellation: some cameras record the same mic
        # on L and R with inverted polarity, so the forced mono downmix
        # (-ac 1) sums to near-silence even though each channel is loud.
        # If the mixed WAV is effectively silent, re-extract single channels
        # and keep the loudest result.
        def _volume(path: str, map_spec: str | None = None,
                    extra_af: str | None = None) -> tuple[float, float] | None:
            """(mean_volume, max_volume) in dB, or None if the probe failed."""
            af = "volumedetect" if not extra_af else f"{extra_af},volumedetect"
            probe = ["ffmpeg", "-i", path]
            if map_spec:
                probe += ["-map", map_spec]
            probe += ["-af", af, "-f", "null", "-"]
            out = subprocess.run(probe, capture_output=True, text=True, timeout=1800)
            if out.returncode != 0:
                return None
            mean = mx = None
            for line in out.stderr.splitlines():
                for key in ("mean_volume", "max_volume"):
                    if f"{key}:" in line:
                        try:
                            val = float(line.split(f"{key}:")[1].split("dB")[0])
                        except ValueError:
                            continue
                        if key == "mean_volume":
                            mean = val
                        else:
                            mx = val
            if mx is None:
                return None
            # If mean failed to parse, assume noise floor so max-based
            # logic still works exactly as before.
            return (mean if mean is not None else -91.0, mx)

        def _channels(path: str, stream_idx: int) -> int:
            try:
                import json as _json
                out = subprocess.run(
                    ["ffprobe", "-v", "error", "-select_streams", f"a:{stream_idx}",
                     "-show_entries", "stream=channels", "-of", "json", path],
                    capture_output=True, text=True, timeout=30,
                )
                streams = _json.loads(out.stdout or "{}").get("streams") or []
                return int(streams[0].get("channels", 1)) if streams else 1
            except Exception:
                return 1

        # Silent when the peak is tiny (< -45 dB) OR when the average level is
        # essentially noise floor (< -70 dB) even if a lone transient (slate
        # clap surviving imperfect cancellation) spikes the peak.
        mix = _volume(audio_path)
        if mix is not None and (mix[1] < -45.0 or mix[0] < -70.0):
            append_log(db, job_id,
                       f"Mono downmix is near-silent (mean {mix[0]:.1f} dB, "
                       f"max {mix[1]:.1f} dB) — probing every source channel "
                       "for phase cancellation")
            # Scan every channel of every mapped audio stream of every input —
            # the same source set the mix used (incl. Curator sidecars).
            candidates = []  # (mean_vol, max_vol, input_idx, stream_idx, channel_idx)
            stream_counts = [max(1, _count_audio_streams(p)) for p in inputs]
            for ii, p in enumerate(inputs):
                for si in range(stream_counts[ii]):
                    for ch in range(_channels(p, si)):
                        vol = _volume(p, map_spec=f"0:a:{si}",
                                      extra_af=f"pan=mono|c0=c{ch}")
                        if vol is not None:
                            candidates.append((vol[0], vol[1], ii, si, ch))
            # Primary criterion (same as before): a usable channel needs real
            # peaks (max > -45). Among those, prefer sustained content
            # (highest mean) so a lone slate-clap channel doesn't win over a
            # channel with actual dialogue; if no channel has sustained
            # content, still recover the loudest-peak channel (old behavior).
            usable = [c for c in candidates if c[1] > -45.0]
            best = None
            if usable:
                sustained = [c for c in usable if c[0] > -70.0]
                best = max(sustained or usable,
                           key=lambda c: (c[0], c[1]) if sustained else (c[1], c[0]))
            if best:
                mean_vol, max_vol, ii, si, ch = best
                append_log(db, job_id, f"Phase cancellation detected — using input "
                           f"{ii} stream {si} channel {ch} only "
                           f"(mean {mean_vol:.1f} dB, max {max_vol:.1f} dB)")
                single = subprocess.run(
                    ["ffmpeg", "-y", "-i", inputs[ii],
                     "-map", f"0:a:{si}", "-vn",
                     "-af", f"pan=mono|c0=c{ch}",
                     "-acodec", "pcm_s16le", "-ar", "16000",
                     audio_path],
                    capture_output=True, text=True, timeout=1800,
                )
                if single.returncode != 0:
                    raise RuntimeError(
                        f"single-channel re-extract failed: {single.stderr[-500:]}")
            else:
                append_log(db, job_id, "All source channels are near-silent — "
                           "keeping downmix (clip has no usable audio)")

        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
        append_log(db, job_id, "Audio extracted successfully")

        # Queue transcription
        from tasks.base import create_job
        trans_job_id = create_job(db, media_id, "transcribe")
        from tasks.transcribe import transcribe_audio
        transcribe_audio.delay(media_id, trans_job_id)

    except Exception as e:
        db.rollback()
        update_job(db, job_id, status="error", error_message=str(e), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()
