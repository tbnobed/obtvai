"""BAGEL keyframe captioning task.

Calls the BAGEL inference service for each scene thumbnail and stores the
natural-language description in scenes.description. This enriches visual
search: CLIP/SigLIP embedding similarity finds visually similar frames,
but BAGEL descriptions enable full-text search over *what is actually in*
each frame ("find the moment Rick Warren holds up a paper").

Queue: cpu  — no local GPU needed; work is HTTP calls to worker-bagel.
"""

import base64
import logging
import os
from datetime import datetime

import httpx

from app import celery_app
from config import BAGEL_SERVICE_URL, THUMBNAILS_DIR
from db import get_session
from tasks.base import append_log, create_job, update_job

logger = logging.getLogger("tasks.bagel_caption")

_CAPTION_TIMEOUT = int(os.environ.get("BAGEL_CAPTION_TIMEOUT", "90"))

_CAPTION_PROMPT = (
    "You are assisting a professional video editor. "
    "Describe this video frame concisely: who is in the frame, "
    "what they are doing, the setting or location, any visible text or "
    "lower-thirds, and the overall mood. Be factual and specific. "
    "Write 2–3 sentences maximum."
)


def _caption_one(thumb_path: str) -> str | None:
    """Send one thumbnail JPEG to BAGEL /caption; return text or None."""
    try:
        with open(thumb_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        r = httpx.post(
            f"{BAGEL_SERVICE_URL}/caption",
            json={"image_b64": b64, "prompt": _CAPTION_PROMPT, "max_tokens": 200},
            timeout=_CAPTION_TIMEOUT,
        )
        r.raise_for_status()
        return r.json().get("caption", "").strip() or None
    except httpx.HTTPStatusError as exc:
        logger.warning("BAGEL /caption HTTP %d", exc.response.status_code)
    except Exception as exc:
        logger.warning("BAGEL /caption error: %s", exc)
    return None


@celery_app.task(bind=True, name="tasks.bagel_caption.caption_scenes", queue="cpu")
def caption_scenes(self, media_id: str, job_id: str):
    db = get_session()
    try:
        update_job(db, job_id, status="running", started_at=datetime.utcnow(), celery_task_id=self.request.id)

        from sqlalchemy import text  # noqa: PLC0415

        # Fail fast if the BAGEL service is unavailable — saves timing out
        # once per scene when the whole service is down.
        try:
            resp = httpx.get(f"{BAGEL_SERVICE_URL}/health", timeout=10)
            if resp.status_code != 200:
                data = resp.json()
                raise RuntimeError(data.get("detail") or f"HTTP {resp.status_code}")
        except Exception as exc:
            msg = f"BAGEL service not reachable ({exc})"
            append_log(db, job_id, msg)
            update_job(db, job_id, status="error", error_message=msg, finished_at=datetime.utcnow())
            return

        scenes = db.execute(
            text("""
                SELECT id, thumbnail_url
                FROM   scenes
                WHERE  media_id    = :mid
                  AND  thumbnail_url IS NOT NULL
                  AND  (description IS NULL OR description = '')
                ORDER  BY start_time
            """),
            {"mid": media_id},
        ).fetchall()

        if not scenes:
            append_log(db, job_id, "All scenes already captioned — nothing to do")
            update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
            return

        append_log(db, job_id, f"Captioning {len(scenes)} scenes with BAGEL")
        done = 0
        for scene_id, thumb_url in scenes:
            thumb_path = os.path.join(THUMBNAILS_DIR, os.path.basename(thumb_url))
            if not os.path.exists(thumb_path):
                continue

            caption = _caption_one(thumb_path)
            if caption:
                db.execute(
                    text("UPDATE scenes SET description = :desc WHERE id = :sid"),
                    {"desc": caption, "sid": scene_id},
                )
                done += 1

            # Commit and report progress every 10 scenes so partial results
            # survive a worker restart.
            if done % 10 == 0 and done > 0:
                db.commit()
                pct = min(99.0, 100.0 * done / len(scenes))
                update_job(db, job_id, progress=pct)
                self.update_state(state="PROGRESS", meta={"done": done, "total": len(scenes)})

        db.commit()
        append_log(db, job_id, f"Captioned {done}/{len(scenes)} scenes")
        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)

    except Exception as exc:
        db.rollback()
        update_job(db, job_id, status="error", error_message=str(exc), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()
