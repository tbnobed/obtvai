"""Social media performance scoring across platforms via the local LLM."""
import json
from datetime import datetime
from app import celery_app
from db import get_session
from tasks.base import update_job, append_log
from tasks.analyze import _load_llm, _generate, _extract_json, _format_timecode
from config import LLM_MODEL

PLATFORMS = ["youtube", "instagram", "x", "facebook", "tiktok"]

# Enough transcript to judge tone/content without blowing the context window.
_MAX_TRANSCRIPT_CHARS = 16000


def _clamp_score(value) -> float:
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _str_list(value, limit=5, maxlen=200) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip()[:maxlen] for v in value if str(v).strip()][:limit]


@celery_app.task(bind=True, name="tasks.social.score_social", queue="gpu")
def score_social(self, media_id: str, job_id: str):
    db = get_session()
    try:
        update_job(db, job_id, status="running", started_at=datetime.utcnow(),
                   celery_task_id=self.request.id, progress=0.0)

        from sqlalchemy import text
        asset = db.execute(
            text("""
                SELECT filename, duration_seconds, synopsis, topics, key_moments
                FROM media_assets WHERE id = :mid
            """),
            {"mid": media_id},
        ).fetchone()
        if not asset:
            raise RuntimeError(f"Media asset {media_id} not found")
        filename, duration_val, synopsis, topics, key_moments = asset
        duration = float(duration_val) if duration_val else 0.0

        rows = db.execute(
            text("""
                SELECT start_time, speaker, text FROM transcript_segments
                WHERE media_id = :mid ORDER BY start_time
            """),
            {"mid": media_id},
        ).fetchall()

        if not rows and not synopsis:
            raise RuntimeError("No transcript or analysis available — process the media first")

        # Sample the transcript: beginning, middle, and end give the LLM the arc.
        transcript_sample = ""
        if rows:
            lines = [
                f"[{_format_timecode(float(r[0]))}] {r[1] or 'Speaker'}: {r[2]}" for r in rows
            ]
            full = "\n".join(lines)
            if len(full) <= _MAX_TRANSCRIPT_CHARS:
                transcript_sample = full
            else:
                third = _MAX_TRANSCRIPT_CHARS // 3
                n = len(lines)
                transcript_sample = (
                    "\n".join(lines)[:third]
                    + "\n[...]\n"
                    + "\n".join(lines[n // 2:])[:third]
                    + "\n[...]\n"
                    + "\n".join(lines[-(n // 4) or -1:])[:third]
                )

        if isinstance(topics, str):
            topics = json.loads(topics)
        if isinstance(key_moments, str):
            key_moments = json.loads(key_moments)

        append_log(db, job_id, f"Loading LLM: {LLM_MODEL}")
        update_job(db, job_id, progress=10.0)
        tokenizer, model = _load_llm()

        append_log(db, job_id, "Scoring social media potential for 5 platforms")
        update_job(db, job_id, progress=30.0)

        context_parts = [f"Video: {filename} (runtime {_format_timecode(duration)})"]
        if synopsis:
            context_parts.append(f"Synopsis: {synopsis}")
        if topics:
            context_parts.append("Topics: " + ", ".join(str(t) for t in topics[:10]))
        if key_moments:
            km_lines = [
                f"- [{_format_timecode(float(km.get('time', 0)))}] {km.get('title', '')}"
                for km in key_moments[:10] if isinstance(km, dict)
            ]
            context_parts.append("Key moments:\n" + "\n".join(km_lines))
        if transcript_sample:
            context_parts.append(f"Transcript excerpts:\n{transcript_sample}")

        prompt = (
            "You are a social media strategist who predicts how video content will "
            "perform on each major platform. Analyze the video below.\n\n"
            + "\n\n".join(context_parts)
            + "\n\nFor EACH platform — youtube, instagram, x, facebook, tiktok — "
            "predict how well this content (or short clips cut from it) would perform, "
            "considering each platform's algorithm, audience, and format preferences "
            "(YouTube: watch time and searchability; Instagram Reels: visual hooks under 90s; "
            "X: newsworthiness and debate; Facebook: shareability with older demographics; "
            "TikTok: hook in the first 3 seconds, trends, under 60s).\n\n"
            "Respond with ONLY a JSON object, no other text, in exactly this shape:\n"
            "{\n"
            '  "platforms": [\n'
            "    {\n"
            '      "platform": "youtube",\n'
            '      "score": 0-100,\n'
            '      "verdict": "one blunt sentence on expected performance",\n'
            '      "strengths": ["specific strength for this platform"],\n'
            '      "weaknesses": ["specific weakness for this platform"],\n'
            '      "best_format": "recommended cut/format for this platform",\n'
            '      "suggested_caption": "ready-to-post caption",\n'
            '      "hashtags": ["#tag1", "#tag2"]\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "Rules: exactly one entry per platform (all 5), scores must differ where the "
            "content genuinely suits platforms differently, 2-3 strengths and weaknesses "
            "each, 3-6 hashtags per platform."
        )

        raw = _generate(tokenizer, model, prompt, max_new_tokens=2500)
        update_job(db, job_id, progress=80.0)

        data = _extract_json(raw)
        entries = data.get("platforms") or []
        by_platform = {}
        for e in entries:
            if not isinstance(e, dict):
                continue
            p = str(e.get("platform", "")).strip().lower()
            if p not in PLATFORMS or p in by_platform:
                continue
            by_platform[p] = {
                "platform": p,
                "score": round(_clamp_score(e.get("score")), 1),
                "verdict": (str(e.get("verdict", "")).strip()[:300] or None),
                "strengths": _str_list(e.get("strengths")),
                "weaknesses": _str_list(e.get("weaknesses")),
                "best_format": (str(e.get("best_format", "")).strip()[:300] or None),
                "suggested_caption": (str(e.get("suggested_caption", "")).strip()[:500] or None),
                "hashtags": _str_list(e.get("hashtags"), limit=8, maxlen=60),
            }

        scores = [by_platform[p] for p in PLATFORMS if p in by_platform]
        if not scores:
            raise RuntimeError(f"LLM returned no usable platform scores: {raw[:300]}")
        missing = [p for p in PLATFORMS if p not in by_platform]
        if missing:
            append_log(db, job_id, f"LLM skipped platforms: {', '.join(missing)}")

        db.execute(
            text("""
                UPDATE media_assets
                SET social_scores = CAST(:scores AS jsonb)
                WHERE id = :mid
            """),
            {"scores": json.dumps(scores), "mid": media_id},
        )
        db.commit()
        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
        append_log(db, job_id, f"Social scoring complete for {len(scores)} platforms")

    except Exception as e:
        db.rollback()
        update_job(db, job_id, status="error", error_message=str(e), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()
