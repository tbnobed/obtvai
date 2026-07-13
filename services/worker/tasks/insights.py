"""Library-wide AI insights: LLM narrative over cross-asset aggregates."""
import json
from datetime import datetime
from app import celery_app
from db import get_session
from tasks.base import update_job, append_log


@celery_app.task(bind=True, name="tasks.insights.generate_insights", queue="gpu")
def generate_insights(self, job_id: str, media_id: str | None = None):
    db = get_session()
    try:
        from sqlalchemy import text
        update_job(db, job_id, status="running", started_at=datetime.utcnow(), celery_task_id=self.request.id)
        append_log(db, job_id, "Aggregating library statistics...")

        total_assets, total_duration = db.execute(
            text("SELECT COUNT(*), COALESCE(SUM(duration_seconds), 0) FROM media_assets")
        ).fetchone()

        top_people = db.execute(
            text("""
                SELECT p.display_name,
                       COUNT(DISTINCT pa.media_id) AS assets,
                       COALESCE(SUM(pa.speaking_seconds), 0) AS secs,
                       p.key_topics
                FROM people p
                JOIN person_appearances pa ON pa.person_id = p.id
                GROUP BY p.id
                ORDER BY assets DESC, secs DESC
                LIMIT 10
            """)
        ).fetchall()

        top_topics = db.execute(
            text("""
                SELECT topic, COUNT(*) AS n
                FROM media_assets, jsonb_array_elements_text(topics) AS topic
                WHERE topics IS NOT NULL
                GROUP BY topic
                ORDER BY n DESC
                LIMIT 15
            """)
        ).fetchall()

        synopses = db.execute(
            text("""
                SELECT filename, synopsis FROM media_assets
                WHERE synopsis IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 15
            """)
        ).fetchall()

        if not total_assets:
            update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
            append_log(db, job_id, "Library is empty — nothing to analyze")
            return

        hours = float(total_duration or 0) / 3600.0
        lines = [f"Library: {total_assets} video assets, {hours:.1f} hours of footage total."]
        if top_people:
            lines.append("\nPeople (by number of assets they appear in):")
            for name, assets, secs, topics in top_people:
                t = f", talks about: {', '.join(topics[:4])}" if topics else ""
                lines.append(f"- {name}: {assets} assets, {float(secs) / 60:.0f} min speaking{t}")
        if top_topics:
            lines.append("\nMost frequent topics: " + ", ".join(f"{t} ({n})" for t, n in top_topics))
        if synopses:
            lines.append("\nRecent asset synopses:")
            for fn, syn in synopses:
                lines.append(f"- {fn}: {syn[:300]}")

        prompt = (
            "You are a media library analyst. Based on the following overview of a "
            "video library, produce key insights an archivist or producer would care "
            "about: recurring people and their roles, dominant themes, coverage gaps, "
            "notable patterns.\n"
            "Respond with ONLY a JSON object of this exact shape:\n"
            '{"headline": "one-sentence overall takeaway about this library", '
            '"insights": [{"title": "short insight title", "detail": "2-3 sentence explanation"}]}\n'
            "Provide 4 to 6 insights.\n\n" + "\n".join(lines)[:16000]
        )

        append_log(db, job_id, "Generating AI narrative...")
        update_job(db, job_id, progress=40.0)
        from tasks.analyze import _load_llm, _generate, _extract_json
        tokenizer, model = _load_llm()
        result = _extract_json(_generate(tokenizer, model, prompt, max_new_tokens=900))

        headline = str(result.get("headline") or "")[:500] or None
        items = result.get("insights")
        cleaned = []
        if isinstance(items, list):
            for it in items[:8]:
                if isinstance(it, dict) and it.get("title") and it.get("detail"):
                    cleaned.append({"title": str(it["title"])[:200], "detail": str(it["detail"])[:1000]})

        db.execute(
            text("""
                INSERT INTO library_insights (id, headline, insights, generated_at)
                VALUES (1, :headline, CAST(:insights AS jsonb), :now)
                ON CONFLICT (id) DO UPDATE SET
                  headline = EXCLUDED.headline,
                  insights = EXCLUDED.insights,
                  generated_at = EXCLUDED.generated_at
            """),
            {"headline": headline, "insights": json.dumps(cleaned), "now": datetime.utcnow()},
        )
        db.commit()

        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
        append_log(db, job_id, f"Insights generated: {len(cleaned)} findings")

    except Exception as e:
        db.rollback()
        update_job(db, job_id, status="error", error_message=str(e), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()
