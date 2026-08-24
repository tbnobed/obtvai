"""Generate a scrub sprite sheet: one JPEG grid of frames sampled across the
whole asset, plus timing metadata. Powers hover-scrubbing in the player and
doubles as the frame source for dense visual embedding (one ffmpeg pass
instead of hundreds of seeks)."""
import json
import math
import os
import subprocess
from datetime import datetime
from app import celery_app
from db import get_session
from tasks.base import update_job, append_log
from config import THUMBNAILS_DIR

TILE_W = 320
TILE_H = 180
COLS = 10
MAX_TILES = 600  # cap sheet size; interval widens on long assets


@celery_app.task(bind=True, name="tasks.sprites.generate_sprite", queue="cpu")
def generate_sprite(self, media_id: str, job_id: str):
    db = get_session()
    try:
        update_job(db, job_id, status="running", started_at=datetime.utcnow(), celery_task_id=self.request.id)

        from sqlalchemy import text
        row = db.execute(
            text("SELECT original_path, proxy_path, duration_seconds FROM media_assets WHERE id = :mid"),
            {"mid": media_id},
        ).fetchone()
        original_path = row[0] if row else None
        proxy_path_db = row[1] if row else None
        duration = float(row[2] or 0) if row else 0.0

        # Prefer the proxy (seekable faststart MP4) but validate it first.
        # Curator WebProxy remuxes can silently produce fragmented MP4s that
        # ffmpeg can't seek, triggering "moov atom not found" in the tile pass.
        def _probe_ok(path: str) -> bool:
            if not path or not os.path.exists(path):
                return False
            p = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=codec_name",
                 "-of", "default=noprint_wrappers=1:nokey=1", path],
                capture_output=True, text=True, timeout=30,
            )
            return p.returncode == 0 and bool(p.stdout.strip())

        if _probe_ok(proxy_path_db):
            video_path = proxy_path_db
        elif _probe_ok(original_path):
            append_log(db, job_id,
                       f"Proxy not seekable — falling back to original for sprite generation")
            video_path = original_path
        else:
            raise FileNotFoundError("No readable video file for sprite generation")
        if duration <= 0:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", video_path],
                capture_output=True, text=True, timeout=60,
            )
            duration = float((probe.stdout or "0").strip() or 0)
        if duration <= 0:
            raise RuntimeError("Could not determine duration for sprite")

        interval = max(1.0, math.ceil(duration / MAX_TILES))
        count = max(1, int(duration // interval) + 1)
        rows = math.ceil(count / COLS)

        os.makedirs(THUMBNAILS_DIR, exist_ok=True)
        sprite_name = f"sprite_{media_id}.jpg"
        sprite_path = os.path.join(THUMBNAILS_DIR, sprite_name)

        append_log(db, job_id, f"Sprite: {count} tiles @ {interval:.0f}s ({COLS}x{rows}, {TILE_W}x{TILE_H})")
        proc = subprocess.run(
            [
                "ffmpeg", "-y", "-i", video_path,
                "-vf", f"fps=1/{interval},scale={TILE_W}:{TILE_H},tile={COLS}x{rows}",
                "-frames:v", "1", "-q:v", "4", sprite_path,
            ],
            capture_output=True, timeout=1800,
        )
        if proc.returncode != 0 or not os.path.exists(sprite_path) or os.path.getsize(sprite_path) == 0:
            tail = (proc.stderr or b"").decode(errors="replace")[-500:]
            raise RuntimeError(f"ffmpeg sprite generation failed: {tail}")

        meta = {
            "interval": interval,
            "tile_width": TILE_W,
            "tile_height": TILE_H,
            "cols": COLS,
            "rows": rows,
            "count": count,
        }
        db.execute(
            text("UPDATE media_assets SET sprite_url = :u, sprite_meta = CAST(:m AS jsonb) WHERE id = :mid"),
            {"u": sprite_name, "m": json.dumps(meta), "mid": media_id},
        )
        db.commit()
        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
        append_log(db, job_id, f"Sprite sheet written: {sprite_name} ({os.path.getsize(sprite_path) // 1024} KB)")

    except Exception as e:
        db.rollback()
        update_job(db, job_id, status="error", error_message=str(e), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()
