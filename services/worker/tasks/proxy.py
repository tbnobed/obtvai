"""Create a browser-compatible H.264/AAC MP4 proxy."""
import os
import subprocess
from datetime import datetime
from app import celery_app
from db import get_session
from tasks.base import update_job, append_log, update_asset
from config import PROXIES_DIR, THUMBNAILS_DIR


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

        cmd = [
            "ffmpeg", "-y", "-i", src,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-progress", "pipe:1", "-nostats",
            proxy_path,
        ]
        import time
        from collections import deque

        # Merge stderr into stdout: a single stream avoids pipe-buffer deadlock
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        last_reported = 0.0
        deadline = time.monotonic() + 3600
        output_tail: deque[str] = deque(maxlen=30)
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                if time.monotonic() > deadline:
                    raise subprocess.TimeoutExpired(cmd, 3600)
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
                            update_job(db, job_id, progress=round(pct, 1))
                elif line and "=" not in line[:20]:
                    output_tail.append(line)
            proc.wait(timeout=60)
        except (subprocess.TimeoutExpired, Exception):
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)
            raise
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg proxy failed: {' | '.join(list(output_tail)[-8:])[:500]}")

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
            thumbnail_url=f"/api/thumbnails/{media_id}.jpg",
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
