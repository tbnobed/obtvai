"""Publish a finished render to YouTube via the Data API (resumable upload)."""
import os
from datetime import datetime
from app import celery_app
from db import get_session
from config import YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN
from tasks.render import _update_render


@celery_app.task(bind=True, name="tasks.publish.publish_render", queue="cpu")
def publish_render(self, render_id: str, title: str, description: str = "",
                   tags: list | None = None, privacy: str = "unlisted"):
    db = get_session()
    try:
        from sqlalchemy import text
        row = db.execute(
            text("SELECT output_path, status FROM render_jobs WHERE id = :rid"),
            {"rid": render_id},
        ).fetchone()
        if not row:
            raise RuntimeError(f"Render job {render_id} not found")
        output_path, status = row
        if status != "success" or not output_path or not os.path.exists(output_path):
            raise RuntimeError("Render output not available for publishing")
        if not (YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN):
            raise RuntimeError("YouTube credentials not configured")

        _update_render(db, render_id, publish_status="running", publish_error=None)

        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        creds = Credentials(
            token=None,
            refresh_token=YOUTUBE_REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=YOUTUBE_CLIENT_ID,
            client_secret=YOUTUBE_CLIENT_SECRET,
            scopes=["https://www.googleapis.com/auth/youtube.upload"],
        )
        youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

        body = {
            "snippet": {
                "title": (title or "Untitled clip")[:100],
                "description": (description or "")[:4900],
                "tags": [t[:100] for t in (tags or [])][:30],
                "categoryId": "25",  # News & Politics; harmless default
            },
            "status": {
                "privacyStatus": privacy if privacy in ("public", "unlisted", "private") else "unlisted",
                "selfDeclaredMadeForKids": False,
            },
        }
        media = MediaFileUpload(output_path, mimetype="video/mp4",
                                chunksize=8 * 1024 * 1024, resumable=True)
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        while response is None:
            _, response = request.next_chunk()

        video_id = response.get("id")
        if not video_id:
            raise RuntimeError(f"YouTube upload returned no video id: {response}")

        _update_render(
            db, render_id,
            publish_status="success",
            publish_url=f"https://www.youtube.com/watch?v={video_id}",
        )

    except Exception as e:
        db.rollback()
        try:
            _update_render(
                db, render_id,
                publish_status="error", publish_error=str(e)[:2000],
            )
        except Exception:
            db.rollback()
        raise
    finally:
        db.close()
