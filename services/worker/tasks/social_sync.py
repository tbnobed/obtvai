"""Sync channel-level growth + per-post metrics for registered social channels.

Programs/channels are managed in the API (social_programs / social_channels);
this task fills social_channel_snapshots (one row per channel per run) and
upserts social_posts by (channel_id, external_id).

Platforms:
- YouTube: Data API v3 with the existing YOUTUBE_API_KEY. channels.list
  resolves @handles (1 unit), playlistItems on the uploads playlist +
  videos.list get recent posts (~3 units/channel/run) — negligible quota.
- Instagram / Facebook: Meta Graph API with META_ACCESS_TOKEN. Owned pages
  read directly; public IG accounts go through business_discovery (requires
  the token's IG business account id in META_IG_USER_ID).
- TikTok: official APIs need per-account OAuth; until TIKTOK_ACCESS_TOKEN is
  wired the channel is marked with a clear last_error instead of failing.

One channel failing must never kill the run — errors land in
social_channels.last_error per channel.
"""
import re
import uuid
from datetime import datetime

import httpx
from sqlalchemy import text

from app import celery_app
from db import get_session
from config import YOUTUBE_API_KEY, META_ACCESS_TOKEN, META_IG_USER_ID, TIKTOK_ACCESS_TOKEN
from tasks.base import update_job, append_log

POSTS_PER_CHANNEL = 12
HTTP_TIMEOUT = 15.0
GRAPH = "https://graph.facebook.com/v21.0"

# Credentials travel in URLs (YouTube ?key=, Graph ?access_token=) and httpx
# exception text includes the full URL — scrub before anything is persisted
# to last_error / job logs, which are rendered in the UI.
_SECRET_RE = re.compile(r"(key|access_token)=[^&\s\"']+", re.IGNORECASE)


def _safe_err(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"{exc.request.url.host} HTTP {exc.response.status_code}"
    return _SECRET_RE.sub(r"\1=***", str(exc))


def _log(db, job_id, message: str):
    if job_id:
        append_log(db, job_id, message)


def _set_channel(db, channel_id: str, **fields):
    sets = ", ".join(f"{k} = :{k}" for k in fields)
    db.execute(
        text(f"UPDATE social_channels SET {sets} WHERE id = :cid"),
        {**fields, "cid": channel_id},
    )
    db.commit()


def _insert_snapshot(db, channel_id: str, followers, total_views, posts_count, now):
    db.execute(
        text("""
            INSERT INTO social_channel_snapshots
                (id, channel_id, fetched_at, followers, total_views, posts_count)
            VALUES (:id, :cid, :ts, :f, :v, :p)
        """),
        {
            "id": str(uuid.uuid4()), "cid": channel_id, "ts": now,
            "f": int(followers) if followers is not None else None,
            "v": int(total_views) if total_views is not None else None,
            "p": int(posts_count) if posts_count is not None else None,
        },
    )


def _upsert_post(db, channel_id: str, platform: str, post: dict, now):
    db.execute(
        text("""
            INSERT INTO social_posts
                (id, channel_id, platform, external_id, title, url, thumbnail_url,
                 published_at, views, likes, comments, shares, fetched_at)
            VALUES
                (:id, :cid, :platform, :ext, :title, :url, :thumb,
                 :pub, :views, :likes, :comments, :shares, :ts)
            ON CONFLICT (channel_id, external_id) DO UPDATE SET
                title = EXCLUDED.title,
                url = EXCLUDED.url,
                thumbnail_url = EXCLUDED.thumbnail_url,
                published_at = EXCLUDED.published_at,
                views = EXCLUDED.views,
                likes = EXCLUDED.likes,
                comments = EXCLUDED.comments,
                shares = EXCLUDED.shares,
                fetched_at = EXCLUDED.fetched_at
        """),
        {
            "id": str(uuid.uuid4()), "cid": channel_id, "platform": platform,
            "ext": str(post["external_id"]),
            "title": (post.get("title") or None) and str(post["title"])[:500],
            "url": post.get("url"), "thumb": post.get("thumbnail_url"),
            "pub": post.get("published_at"),
            "views": _i(post.get("views")), "likes": _i(post.get("likes")),
            "comments": _i(post.get("comments")), "shares": _i(post.get("shares")),
            "ts": now,
        },
    )


def _i(v):
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# ── YouTube ──────────────────────────────────────────────────────────────────

def _yt_get(client, path, **params):
    params["key"] = YOUTUBE_API_KEY
    r = client.get(f"https://www.googleapis.com/youtube/v3/{path}", params=params)
    r.raise_for_status()
    return r.json()


def _sync_youtube(db, client, ch, now):
    handle = ch["handle"].lstrip("@")
    ext_id = ch["external_id"]
    if not ext_id:
        data = _yt_get(client, "channels", part="id", forHandle=handle)
        items = data.get("items") or []
        if not items:
            raise RuntimeError(f"YouTube channel not found for handle @{handle}")
        ext_id = items[0]["id"]

    data = _yt_get(client, "channels", part="snippet,statistics,contentDetails", id=ext_id)
    items = data.get("items") or []
    if not items:
        raise RuntimeError("YouTube channel id no longer resolves")
    item = items[0]
    sn, st = item.get("snippet", {}), item.get("statistics", {})
    _set_channel(
        db, ch["id"],
        external_id=ext_id,
        display_name=(sn.get("title") or None),
        avatar_url=((sn.get("thumbnails") or {}).get("default") or {}).get("url"),
    )
    _insert_snapshot(
        db, ch["id"],
        st.get("subscriberCount"), st.get("viewCount"), st.get("videoCount"), now,
    )

    uploads = ((item.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
    if not uploads:
        return
    pl = _yt_get(client, "playlistItems", part="contentDetails", playlistId=uploads,
                 maxResults=POSTS_PER_CHANNEL)
    video_ids = [
        (it.get("contentDetails") or {}).get("videoId")
        for it in pl.get("items", [])
    ]
    video_ids = [v for v in video_ids if v]
    if not video_ids:
        return
    vids = _yt_get(client, "videos", part="snippet,statistics", id=",".join(video_ids))
    for v in vids.get("items", []):
        vsn, vst = v.get("snippet", {}), v.get("statistics", {})
        _upsert_post(db, ch["id"], "youtube", {
            "external_id": v["id"],
            "title": vsn.get("title"),
            "url": f"https://www.youtube.com/watch?v={v['id']}",
            "thumbnail_url": ((vsn.get("thumbnails") or {}).get("medium") or {}).get("url"),
            "published_at": vsn.get("publishedAt"),
            "views": vst.get("viewCount"),
            "likes": vst.get("likeCount"),
            "comments": vst.get("commentCount"),
        }, now)
    db.commit()


# ── Meta (Instagram + Facebook) ──────────────────────────────────────────────

def _graph_get(client, path, **params):
    params["access_token"] = META_ACCESS_TOKEN
    r = client.get(f"{GRAPH}/{path}", params=params)
    body = r.json()
    if "error" in body:
        raise RuntimeError(body["error"].get("message") or "Graph API error")
    r.raise_for_status()
    return body


def _sync_instagram(db, client, ch, now):
    """Public IG accounts via business_discovery on our own IG business user."""
    if not META_IG_USER_ID:
        raise RuntimeError("META_IG_USER_ID not configured (required for Instagram business_discovery)")
    handle = ch["handle"].lstrip("@")
    fields = (
        f"business_discovery.username({handle})"
        "{id,username,name,profile_picture_url,followers_count,media_count,"
        f"media.limit({POSTS_PER_CHANNEL})"
        "{id,caption,permalink,media_url,thumbnail_url,timestamp,like_count,comments_count}}"
    )
    data = _graph_get(client, META_IG_USER_ID, fields=fields)
    bd = data.get("business_discovery") or {}
    if not bd:
        raise RuntimeError(f"Instagram account @{handle} not discoverable (must be a business/creator account)")
    _set_channel(
        db, ch["id"],
        external_id=str(bd.get("id")),
        display_name=bd.get("name") or bd.get("username"),
        avatar_url=bd.get("profile_picture_url"),
    )
    _insert_snapshot(db, ch["id"], bd.get("followers_count"), None, bd.get("media_count"), now)
    for m in (bd.get("media") or {}).get("data", []):
        _upsert_post(db, ch["id"], "instagram", {
            "external_id": m["id"],
            "title": (m.get("caption") or "")[:200] or None,
            "url": m.get("permalink"),
            "thumbnail_url": m.get("thumbnail_url") or m.get("media_url"),
            "published_at": m.get("timestamp"),
            "likes": m.get("like_count"),
            "comments": m.get("comments_count"),
        }, now)
    db.commit()


def _sync_facebook(db, client, ch, now):
    """Facebook Pages. Owned pages get full metrics; public pages only what
    the Graph API exposes without page tokens (name, fan_count)."""
    ident = ch["external_id"] or ch["handle"].lstrip("@")
    page = _graph_get(client, ident, fields="id,name,fan_count,followers_count,picture{url}")
    _set_channel(
        db, ch["id"],
        external_id=str(page.get("id")),
        display_name=page.get("name"),
        avatar_url=((page.get("picture") or {}).get("data") or {}).get("url"),
    )
    followers = page.get("followers_count", page.get("fan_count"))
    _insert_snapshot(db, ch["id"], followers, None, None, now)
    try:
        posts = _graph_get(
            client, f"{page['id']}/posts",
            fields="id,message,permalink_url,created_time,full_picture,"
                   "shares,likes.summary(true),comments.summary(true)",
            limit=POSTS_PER_CHANNEL,
        )
        for p in posts.get("data", []):
            _upsert_post(db, ch["id"], "facebook", {
                "external_id": p["id"],
                "title": (p.get("message") or "")[:200] or None,
                "url": p.get("permalink_url"),
                "thumbnail_url": p.get("full_picture"),
                "published_at": p.get("created_time"),
                "likes": ((p.get("likes") or {}).get("summary") or {}).get("total_count"),
                "comments": ((p.get("comments") or {}).get("summary") or {}).get("total_count"),
                "shares": (p.get("shares") or {}).get("count"),
            }, now)
    except RuntimeError:
        # Post-level data needs a page access token for pages we don't own;
        # channel-level snapshot above still succeeded, so don't fail the channel.
        pass
    db.commit()


# ── Task ─────────────────────────────────────────────────────────────────────

@celery_app.task(bind=True, name="tasks.social_sync.sync_social_channels", queue="cpu")
def sync_social_channels(self, job_id: str | None = None, media_id: str | None = None):
    db = get_session()
    try:
        if job_id:
            update_job(db, job_id, status="running", started_at=datetime.utcnow(), progress=5)

        channels = [
            dict(r._mapping) for r in db.execute(text(
                "SELECT id, program_id, platform, handle, external_id FROM social_channels"
            )).fetchall()
        ]
        if not channels:
            _log(db, job_id, "No social channels configured")
            if job_id:
                update_job(db, job_id, status="success", progress=100,
                           finished_at=datetime.utcnow())
            return {"channels": 0, "synced": 0}

        now = datetime.utcnow()
        synced, failed = 0, 0
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            for idx, ch in enumerate(channels):
                platform = ch["platform"]
                try:
                    if platform == "youtube":
                        if not YOUTUBE_API_KEY:
                            raise RuntimeError("YOUTUBE_API_KEY not configured")
                        _sync_youtube(db, client, ch, now)
                    elif platform == "instagram":
                        if not META_ACCESS_TOKEN:
                            raise RuntimeError("META_ACCESS_TOKEN not configured")
                        _sync_instagram(db, client, ch, now)
                    elif platform == "facebook":
                        if not META_ACCESS_TOKEN:
                            raise RuntimeError("META_ACCESS_TOKEN not configured")
                        _sync_facebook(db, client, ch, now)
                    elif platform == "tiktok":
                        raise RuntimeError(
                            "TikTok API credentials not configured"
                            if not TIKTOK_ACCESS_TOKEN
                            else "TikTok sync not yet implemented"
                        )
                    else:
                        raise RuntimeError(f"Unknown platform: {platform}")
                    _set_channel(db, ch["id"], last_sync_at=now, last_error=None)
                    synced += 1
                    _log(db, job_id, f"Synced {platform} {ch['handle']}")
                except Exception as exc:
                    db.rollback()
                    failed += 1
                    err = _safe_err(exc)
                    _set_channel(db, ch["id"], last_error=err[:500])
                    _log(db, job_id, f"{platform} {ch['handle']} failed: {err}")
                if job_id:
                    update_job(db, job_id,
                               progress=5 + int(90 * (idx + 1) / len(channels)))

        if synced == 0 and failed > 0:
            raise RuntimeError(f"All {failed} channels failed to sync")

        if job_id:
            update_job(db, job_id, status="success", progress=100,
                       finished_at=datetime.utcnow())
        return {"channels": len(channels), "synced": synced, "failed": failed}
    except Exception as exc:
        db.rollback()
        if job_id:
            update_job(db, job_id, status="error", error_message=_safe_err(exc)[:500],
                       finished_at=datetime.utcnow())
        raise
    finally:
        db.close()
