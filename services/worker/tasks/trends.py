"""Fetch external trend signals so the library can be correlated with what is
happening outside the building: YouTube trending videos (Data API) and web
news momentum for the library's own topics (self-hosted SearXNG).

Runs on a Celery beat schedule (every 3 h) and can be triggered manually via
POST /trends/refresh. Privacy boundary: only topic keywords / search queries
ever leave the network — never media, transcripts, or embeddings.
"""
import json
import uuid
from datetime import datetime

import httpx
from sqlalchemy import text

from app import celery_app
from db import get_session
from config import SEARXNG_URL, TRENDS_REGION
from topic_norm import normalize_topic_key, group_topics
from tasks.base import update_job, append_log

YOUTUBE_TRENDING_MAX = 50   # one videos.list call, 1 quota unit
WEB_TOPIC_LIMIT = 25        # top library topics queried against SearXNG
WEB_HEADLINES_KEPT = 3
SEARX_TIMEOUT = 10.0
SEARX_MAX_CONSECUTIVE_FAILURES = 3  # abort early instead of 25 timeouts


def _log(db, job_id, message: str):
    if job_id:
        append_log(db, job_id, message)


def _norm_haystack(*parts) -> str:
    """One normalized token string per trend for read-time topic matching."""
    toks: list[str] = []
    for p in parts:
        if not p:
            continue
        if isinstance(p, (list, tuple)):
            toks.extend(str(x) for x in p)
        else:
            toks.append(str(p))
    return normalize_topic_key(" ".join(toks))


def _replace_source(db, source: str, rows: list[dict]):
    """Swap a source's trend rows atomically (delete + insert, one commit)."""
    db.execute(text("DELETE FROM trend_topics WHERE source = :s"), {"s": source})
    for r in rows:
        db.execute(
            text("""
                INSERT INTO trend_topics
                    (id, source, label, topic_key, rank, score, meta, fetched_at)
                VALUES
                    (:id, :source, :label, :topic_key, :rank, :score,
                     CAST(:meta AS jsonb), :fetched_at)
            """),
            r,
        )
    db.commit()


def _fetch_youtube(db, job_id) -> int:
    from tasks.social_stats import _build_client

    yt = _build_client()
    if yt is None:
        _log(db, job_id, "YouTube trends skipped: no YouTube credentials configured")
        return 0

    resp = yt.videos().list(
        part="snippet,statistics",
        chart="mostPopular",
        regionCode=TRENDS_REGION,
        maxResults=YOUTUBE_TRENDING_MAX,
    ).execute()

    now = datetime.utcnow()
    rows = []
    for rank, item in enumerate(resp.get("items", []), start=1):
        sn = item.get("snippet", {}) or {}
        stats = item.get("statistics", {}) or {}
        title = sn.get("title") or ""
        if not title:
            continue
        views = int(stats.get("viewCount", 0) or 0)
        rows.append({
            "id": str(uuid.uuid4()),
            "source": "youtube",
            "label": title[:300],
            "topic_key": None,
            "rank": rank,
            "score": float(views),
            "meta": json.dumps({
                "url": f"https://www.youtube.com/watch?v={item.get('id')}",
                "channel": sn.get("channelTitle"),
                "views": views,
                # Normalized once at fetch time so the API can do cheap
                # token-boundary matching against library topic keys.
                "haystack": _norm_haystack(title, sn.get("tags"), sn.get("channelTitle")),
            }),
            "fetched_at": now,
        })

    _replace_source(db, "youtube", rows)
    _log(db, job_id, f"YouTube: stored {len(rows)} trending videos ({TRENDS_REGION})")
    return len(rows)


def _fetch_web(db, job_id) -> int:
    if not SEARXNG_URL:
        _log(db, job_id, "Web trends skipped: SEARXNG_URL not configured")
        return 0

    raw = db.execute(text("""
        SELECT topic, COUNT(DISTINCT id) AS n
        FROM media_assets, jsonb_array_elements_text(topics) AS topic
        WHERE topics IS NOT NULL
        GROUP BY topic
    """)).fetchall()
    topics = group_topics((t, int(n)) for t, n in raw)[:WEB_TOPIC_LIMIT]
    if not topics:
        _log(db, job_id, "Web trends skipped: no library topics extracted yet")
        return 0

    now = datetime.utcnow()
    rows = []
    consecutive_failures = 0
    base = SEARXNG_URL.rstrip("/")
    with httpx.Client(timeout=SEARX_TIMEOUT) as client:
        for rank, g in enumerate(topics, start=1):
            try:
                resp = client.get(
                    f"{base}/search",
                    params={
                        "q": g["topic"],
                        "format": "json",
                        "categories": "news",
                        "time_range": "week",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                consecutive_failures = 0
            except Exception as exc:
                consecutive_failures += 1
                _log(db, job_id, f"SearXNG query failed for '{g['topic']}': {exc}")
                if consecutive_failures >= SEARX_MAX_CONSECUTIVE_FAILURES:
                    # SearXNG is down, not one flaky query — keep the stale
                    # rows rather than wiping them with an empty batch.
                    raise RuntimeError(
                        f"SearXNG unreachable at {base} "
                        f"({consecutive_failures} consecutive failures)"
                    )
                continue

            results = data.get("results") or []
            rows.append({
                "id": str(uuid.uuid4()),
                "source": "web",
                "label": g["topic"][:300],
                "topic_key": g["key"],
                "rank": rank,
                "score": float(len(results)),
                "meta": json.dumps({
                    "headlines": [
                        {"title": (r.get("title") or "")[:300], "url": r.get("url")}
                        for r in results[:WEB_HEADLINES_KEPT]
                    ],
                }),
                "fetched_at": now,
            })

    _replace_source(db, "web", rows)
    _log(db, job_id, f"Web: stored news momentum for {len(rows)} library topics")
    return len(rows)


@celery_app.task(bind=True, name="tasks.trends.fetch_trends", queue="cpu")
def fetch_trends(self, job_id: str | None = None, media_id: str | None = None):
    db = get_session()
    try:
        if job_id:
            update_job(db, job_id, status="running", started_at=datetime.utcnow(), progress=5)

        errors: list[str] = []
        yt_count = web_count = 0

        try:
            yt_count = _fetch_youtube(db, job_id)
        except Exception as exc:
            db.rollback()
            errors.append(f"youtube: {exc}")
            _log(db, job_id, f"YouTube trends failed: {exc}")

        if job_id:
            update_job(db, job_id, progress=50)

        try:
            web_count = _fetch_web(db, job_id)
        except Exception as exc:
            db.rollback()
            errors.append(f"web: {exc}")
            _log(db, job_id, f"Web trends failed: {exc}")

        # One source failing shouldn't kill the other; error only if both did.
        if errors and not (yt_count or web_count):
            raise RuntimeError("; ".join(errors))

        if job_id:
            update_job(
                db, job_id,
                status="success", progress=100, finished_at=datetime.utcnow(),
            )
        return {"youtube": yt_count, "web": web_count, "errors": errors}
    except Exception as exc:
        db.rollback()
        if job_id:
            update_job(
                db, job_id,
                status="error", error_message=str(exc)[:500],
                finished_at=datetime.utcnow(),
            )
        raise
    finally:
        db.close()
