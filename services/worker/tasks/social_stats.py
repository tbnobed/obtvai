"""Pull real YouTube performance stats for published renders via the Data API.

Runs on a Celery beat schedule (hourly) and can also be triggered manually.
videos.list(part=statistics) costs 1 quota unit per call and accepts up to 50
video ids, so polling the whole published catalog is essentially free against
the 10k/day quota.
"""
import re
from datetime import datetime
from app import celery_app
from db import get_session
from config import (
    YOUTUBE_CLIENT_ID,
    YOUTUBE_CLIENT_SECRET,
    YOUTUBE_REFRESH_TOKEN,
    YOUTUBE_API_KEY,
)

_VIDEO_ID_RE = re.compile(r"[?&]v=([A-Za-z0-9_-]{6,})")


def _extract_video_id(url: str) -> str | None:
    m = _VIDEO_ID_RE.search(url or "")
    if m:
        return m.group(1)
    m = re.search(r"youtu\.be/([A-Za-z0-9_-]{6,})", url or "")
    return m.group(1) if m else None


def _build_client():
    from googleapiclient.discovery import build

    # An API key is enough for videos.list statistics (public/unlisted by id)
    # and avoids scope issues with the upload-only OAuth token.
    if YOUTUBE_API_KEY:
        return build("youtube", "v3", developerKey=YOUTUBE_API_KEY, cache_discovery=False)
    if YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN:
        from google.oauth2.credentials import Credentials

        creds = Credentials(
            token=None,
            refresh_token=YOUTUBE_REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=YOUTUBE_CLIENT_ID,
            client_secret=YOUTUBE_CLIENT_SECRET,
        )
        return build("youtube", "v3", credentials=creds, cache_discovery=False)
    return None


@celery_app.task(bind=True, name="tasks.social_stats.sync_youtube_stats", queue="cpu")
def sync_youtube_stats(self):
    db = get_session()
    try:
        from sqlalchemy import text

        rows = db.execute(text(
            "SELECT id, publish_url FROM render_jobs "
            "WHERE publish_status = 'success' AND publish_url IS NOT NULL"
        )).fetchall()

        by_video: dict[str, list[str]] = {}
        for render_id, url in rows:
            vid = _extract_video_id(url)
            if vid:
                by_video.setdefault(vid, []).append(render_id)

        if not by_video:
            return {"videos": 0, "updated": 0}

        youtube = _build_client()
        if youtube is None:
            raise RuntimeError("No YouTube credentials configured (YOUTUBE_API_KEY or OAuth trio)")

        video_ids = list(by_video.keys())
        updated = 0
        fetched_at = datetime.utcnow().isoformat() + "Z"

        for i in range(0, len(video_ids), 50):
            batch = video_ids[i:i + 50]
            resp = youtube.videos().list(part="statistics", id=",".join(batch)).execute()
            for item in resp.get("items", []):
                stats = item.get("statistics", {}) or {}
                payload = {
                    "platform": "youtube",
                    "views": int(stats.get("viewCount", 0) or 0),
                    "likes": int(stats.get("likeCount", 0) or 0),
                    "comments": int(stats.get("commentCount", 0) or 0),
                    "fetched_at": fetched_at,
                }
                import json as _json
                for render_id in by_video.get(item["id"], []):
                    db.execute(
                        text("UPDATE render_jobs SET publish_stats = CAST(:s AS jsonb) WHERE id = :rid"),
                        {"s": _json.dumps(payload), "rid": render_id},
                    )
                    updated += 1
            db.commit()

        return {"videos": len(video_ids), "updated": updated}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
