"""Create a browser-compatible H.264/AAC MP4 proxy."""
import os
import subprocess
import time
from collections import deque
from datetime import datetime
from app import celery_app
from db import get_session
from tasks.base import update_job, append_log, update_asset
from config import PROXIES_DIR, THUMBNAILS_DIR


def _run_ffmpeg_with_progress(cmd, duration, on_progress, timeout=3600):
    """Run ffmpeg, streaming -progress output. Returns (returncode, output_tail).

    stderr is merged into stdout: a single stream avoids pipe-buffer deadlock.
    """
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    deadline = time.monotonic() + timeout
    last_reported = 0.0
    output_tail: deque[str] = deque(maxlen=30)
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if time.monotonic() > deadline:
                raise subprocess.TimeoutExpired(cmd, timeout)
            line = line.strip()
            if line.startswith("out_time_ms="):
                if duration > 0:
                    try:
                        out_sec = int(line.split("=", 1)[1]) / 1_000_000
                    except ValueError:
                        continue
                    pct = min(99.0, (out_sec / duration) * 100.0)
                    if pct - last_reported >= 5.0:
                        last_reported = pct
                        on_progress(round(pct, 1))
            elif line and "=" not in line[:20]:
                output_tail.append(line)
        proc.wait(timeout=60)
    except (subprocess.TimeoutExpired, Exception):
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
        raise
    return proc.returncode, " | ".join(list(output_tail)[-8:])[:500]


# (encoder label, video codec args). NVENC uses the GPU's dedicated hardware
# encoder; libx264 is the CPU fallback when NVENC is unavailable.
_ENCODERS = [
    ("h264_nvenc (GPU)", ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "23", "-b:v", "0"]),
    ("libx264 (CPU)", ["-c:v", "libx264", "-preset", "fast", "-crf", "23"]),
]


@celery_app.task(bind=True, name="tasks.proxy.create_proxy", queue="cpu")
def create_proxy(self, media_id: str, job_id: str):
    db = get_session()
    try:
        update_job(db, job_id, status="running", started_at=datetime.utcnow(), celery_task_id=self.request.id)
        update_asset(db, media_id, processing_stage="proxy", processing_progress=25.0)

        from sqlalchemy import text
        row = db.execute(text("SELECT original_path FROM media_assets WHERE id = :mid"), {"mid": media_id}).fetchone()
        src = row[0]

        os.makedirs(PROXIES_DIR, exist_ok=True)
        os.makedirs(THUMBNAILS_DIR, exist_ok=True)

        proxy_path = os.path.join(PROXIES_DIR, f"{media_id}.mp4")
        append_log(db, job_id, f"Creating proxy at {proxy_path}")

        dur_row = db.execute(text("SELECT duration_seconds FROM media_assets WHERE id = :mid"), {"mid": media_id}).fetchone()
        duration = float(dur_row[0]) if dur_row and dur_row[0] else 0.0

        def report(pct: float):
            update_job(db, job_id, progress=pct)

        # Reuse an existing IPV Curator WebProxy render when one matches this
        # source — no re-encode, no duplicate media. The proxy path stays a
        # symlink inside PROXIES_DIR so serving/cleanup work unchanged.
        external = None
        rc, tail = -1, ""
        try:
            from tasks.curator import find_curator_proxy
            external = find_curator_proxy(src)
        except Exception as e:
            append_log(db, job_id, f"Curator proxy lookup failed (falling back to encode): {e}")

        if external:
            append_log(db, job_id, f"Reusing existing Curator proxy: {external}")
            if os.path.islink(proxy_path) or os.path.exists(proxy_path):
                os.remove(proxy_path)
            os.symlink(external, proxy_path)
            rc, tail = 0, ""

        for label, codec_args in ([] if external else _ENCODERS):
            cmd = [
                "ffmpeg", "-y", "-i", src,
                *codec_args,
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                "-progress", "pipe:1", "-nostats",
                proxy_path,
            ]
            append_log(db, job_id, f"Encoding with {label}...")
            rc, tail = _run_ffmpeg_with_progress(cmd, duration, report)
            if rc == 0:
                append_log(db, job_id, f"Encode succeeded with {label}")
                break
            append_log(db, job_id, f"{label} failed (exit {rc}): {tail[:200]}")

        if rc != 0:
            raise RuntimeError(f"ffmpeg proxy failed with all encoders: {tail}")

        # Extract thumbnail at 10% of duration
        thumb_path = os.path.join(THUMBNAILS_DIR, f"{media_id}.jpg")
        seek = max(1, int((duration or 30) * 0.1))
        thumb_cmd = [
            "ffmpeg", "-y", "-ss", str(seek), "-i", proxy_path,
            "-vframes", "1", "-q:v", "2", thumb_path,
        ]
        subprocess.run(thumb_cmd, capture_output=True, timeout=30)

        update_asset(db, media_id,
            proxy_path=proxy_path,
            thumbnail_url=f"{media_id}.jpg",
            processing_stage="proxy_complete",
            processing_progress=40.0,
        )
        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
        append_log(db, job_id, "Proxy created successfully")

    except Exception as e:
        db.rollback()
        update_job(db, job_id, status="error", error_message=str(e), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()
