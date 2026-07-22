"""Technical QC pass: audio clipping, silence, and black-frame detection via ffmpeg."""
import re
import subprocess
from datetime import datetime
from app import celery_app
from db import get_session
from tasks.base import update_job, append_log


@celery_app.task(bind=True, name="tasks.qc.run_qc", queue="cpu")
def run_qc(self, media_id: str, job_id: str = None):
    db = get_session()
    try:
        update_job(db, job_id, status="running", started_at=datetime.utcnow(), celery_task_id=self.request.id)

        from sqlalchemy import text
        row = db.execute(
            text("SELECT original_path, duration_seconds FROM media_assets WHERE id = :mid"),
            {"mid": media_id},
        ).fetchone()
        if not row or not row[0]:
            raise ValueError("No source file path for asset")
        src_path = row[0]
        duration = float(row[1] or 0)

        append_log(db, job_id, f"Running technical QC on: {src_path}")
        update_job(db, job_id, progress=10.0)

        flags = []
        qc = {"flags": flags}

        # ── Audio analysis (volumedetect) ────────────────────────────────
        # Curator proxies are video-only; their audio lives in sidecar
        # _audioN.mp4 files next to the video. Analyze those instead so the
        # asset isn't falsely flagged no_audio.
        audio_paths = [src_path]
        from tasks.curator import is_curator_video, has_audio_stream, find_curator_audio
        if is_curator_video(src_path) and not has_audio_stream(src_path):
            sidecars = find_curator_audio(src_path)
            if sidecars:
                audio_paths = sidecars
                append_log(db, job_id, f"Video-only Curator proxy — analyzing sidecar audio: "
                                       f"{[s.split('/')[-1] for s in sidecars]}")

        append_log(db, job_id, "Analyzing audio levels (volumedetect)...")
        max_vol = None
        mean_vol = None
        for ap in audio_paths:
            audio_out = _run_ffmpeg_filter(ap, ["-af", "volumedetect", "-vn"])
            mv = _grep_float(audio_out, r"max_volume:\s*(-?[\d.]+)\s*dB")
            av = _grep_float(audio_out, r"mean_volume:\s*(-?[\d.]+)\s*dB")
            if mv is not None and (max_vol is None or mv > max_vol):
                max_vol = mv
            if av is not None and (mean_vol is None or av > mean_vol):
                mean_vol = av
        has_audio = max_vol is not None
        qc["max_volume_db"] = max_vol
        qc["mean_volume_db"] = mean_vol

        if not has_audio:
            flags.append("no_audio")
        else:
            if max_vol >= -0.1:
                flags.append("audio_clipping")
            if mean_vol is not None and mean_vol < -50.0:
                flags.append("audio_silent")
            elif mean_vol is not None and mean_vol < -35.0:
                flags.append("audio_low")
        update_job(db, job_id, progress=50.0)

        # ── Black frame detection ────────────────────────────────────────
        append_log(db, job_id, "Detecting black segments (blackdetect)...")
        black_out = _run_ffmpeg_filter(src_path, ["-vf", "blackdetect=d=1.0:pix_th=0.10", "-an"])
        black_segments = []
        for m in re.finditer(r"black_start:([\d.]+)\s+black_end:([\d.]+)\s+black_duration:([\d.]+)", black_out):
            black_segments.append({
                "start": round(float(m.group(1)), 2),
                "end": round(float(m.group(2)), 2),
                "duration": round(float(m.group(3)), 2),
            })
        total_black = sum(s["duration"] for s in black_segments)
        qc["black_segments"] = black_segments[:50]
        qc["black_seconds"] = round(total_black, 2)
        if black_segments:
            flags.append("black_frames")
        if duration > 0 and total_black / duration > 0.9:
            flags.append("mostly_black")

        append_log(db, job_id, f"QC flags: {flags or ['clean']}")
        import json
        db.execute(
            text("UPDATE media_assets SET qc_flags = CAST(:qc AS jsonb) WHERE id = :mid"),
            {"qc": json.dumps(qc), "mid": media_id},
        )
        db.commit()
        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)

    except Exception as e:
        db.rollback()
        update_job(db, job_id or "unknown", status="error", error_message=str(e), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()


def _run_ffmpeg_filter(path: str, filter_args: list) -> str:
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", path, *filter_args, "-f", "null", "-"]
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=1800
    )
    return result.stdout or ""


def _grep_float(text: str, pattern: str):
    m = re.search(pattern, text)
    return float(m.group(1)) if m else None
