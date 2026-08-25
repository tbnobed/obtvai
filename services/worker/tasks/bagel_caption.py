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

_CAPTION_TIMEOUT = int(os.environ.get("BAGEL_CAPTION_TIMEOUT", "600"))
_CAPTION_MAX_TOKENS = int(os.environ.get("BAGEL_CAPTION_MAX_TOKENS", "120"))
_MAX_CONSECUTIVE_FAILURES = int(os.environ.get("BAGEL_MAX_CONSECUTIVE_FAILURES", "3"))

_CAPTION_PROMPT = (
    "You are assisting a professional video editor. "
    "Describe this video frame concisely: who is in the frame, "
    "what they are doing, the setting or location, any visible text or "
    "lower-thirds, and the overall mood. Be factual and specific. "
    "Write 2–3 sentences maximum."
)


def _caption_one(client: httpx.Client, thumb_path: str) -> tuple[str | None, str | None]:
    """Send one thumbnail JPEG to BAGEL /caption; return (text, error)."""
    try:
        with open(thumb_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        r = client.post(
            f"{BAGEL_SERVICE_URL}/caption",
            json={"image_b64": b64, "prompt": _CAPTION_PROMPT, "max_tokens": _CAPTION_MAX_TOKENS},
        )
        r.raise_for_status()
        caption = r.json().get("caption", "").strip() or None
        return caption, None if caption else "empty caption"
    except httpx.HTTPStatusError as exc:
        logger.warning("BAGEL /caption HTTP %d", exc.response.status_code)
        return None, f"HTTP {exc.response.status_code}"
    except httpx.TimeoutException:
        logger.warning("BAGEL /caption timed out after %ss", _CAPTION_TIMEOUT)
        return None, f"timeout after {_CAPTION_TIMEOUT}s"
    except Exception as exc:
        logger.warning("BAGEL /caption error: %s", exc)
        return None, str(exc)


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

        total = len(scenes)
        append_log(db, job_id, f"Captioning {total} scenes with BAGEL")
        captioned = 0
        attempted = 0
        consecutive_failures = 0
        with httpx.Client(timeout=_CAPTION_TIMEOUT) as client:
            for scene_id, thumb_url in scenes:
                # Let the UI Cancel action stop a long batch between requests.
                current_status = db.execute(
                    text("SELECT status FROM processing_jobs WHERE id = :jid"),
                    {"jid": job_id},
                ).scalar()
                if current_status in ("cancelled", "error"):
                    append_log(db, job_id, f"Captioning stopped with status {current_status}")
                    return

                attempted += 1
                thumb_path = os.path.join(THUMBNAILS_DIR, os.path.basename(thumb_url))
                caption, failure = (
                    _caption_one(client, thumb_path)
                    if os.path.exists(thumb_path)
                    else (None, "missing thumbnail")
                )
                if caption:
                    consecutive_failures = 0
                    db.execute(
                        text("UPDATE scenes SET description = :desc WHERE id = :sid"),
                        {"desc": caption, "sid": scene_id},
                    )
                    captioned += 1
                elif failure != "missing thumbnail":
                    consecutive_failures += 1

                # Report attempted frames, not only successful captions. This
                # keeps progress/heartbeat moving when BAGEL returns an empty
                # caption or an individual frame fails.
                pct = min(99.0, 100.0 * attempted / total)
                update_job(db, job_id, progress=pct)
                self.update_state(
                    state="PROGRESS",
                    meta={"attempted": attempted, "captioned": captioned, "total": total},
                )
                if attempted % 10 == 0 or attempted == total:
                    append_log(db, job_id, f"Processed {attempted}/{total} scenes ({captioned} captions)")
                if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                    raise RuntimeError(
                        f"BAGEL failed {consecutive_failures} consecutive scenes; "
                        f"last error: {failure}"
                    )

        append_log(db, job_id, f"Captioned {captioned}/{total} scenes")
        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)

    except Exception as exc:
        db.rollback()
        update_job(db, job_id, status="error", error_message=str(exc), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()
