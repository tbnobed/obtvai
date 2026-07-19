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

        # Asset catalog for resolving LLM filename references back to ids.
        asset_rows = db.execute(
            text("""
                SELECT id, filename, COALESCE(duration_seconds, 0) AS dur
                FROM media_assets
                ORDER BY created_at DESC
                LIMIT 60
            """)
        ).fetchall()
        assets_by_filename = {fn.lower(): (aid, float(dur)) for aid, fn, dur in asset_rows}

        person_rows = db.execute(
            text("SELECT id, display_name FROM people")
        ).fetchall()
        people_by_name = {name.lower(): pid for pid, name in person_rows}

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
        if asset_rows:
            lines.append("\nAsset files (filename, minutes):")
            for _aid, fn, dur in asset_rows:
                lines.append(f"- {fn} ({float(dur) / 60:.0f} min)")

        from tasks.analyze import CREATIVE_PERSONA
        prompt = (
            "You are a media library analyst. " + CREATIVE_PERSONA + "\n"
            "Based on the following overview of a "
            "video library, produce key insights an archivist or producer would care "
            "about: recurring people and their roles, dominant themes, coverage gaps, "
            "story and series opportunities hiding in the footage, notable patterns.\n"
            "Respond with ONLY a JSON object of this exact shape:\n"
            '{"headline": "one-sentence overall takeaway about this library", '
            '"insights": [{"title": "short insight title", "detail": "2-3 sentence explanation", '
            '"related_people": ["exact person name from the People list"], '
            '"related_topics": ["topic name"]}], '
            '"opportunities": [{"title": "working title for a producible story", '
            '"rationale": "2-3 sentences on why this story is sitting in the footage", '
            '"asset_filenames": ["exact filename from the Asset files list"], '
            '"people": ["exact person name"]}], '
            '"coverage_gaps": ["topic that is thin or missing given what the library is clearly about"]}\n'
            "Provide 4 to 6 insights, 2 to 3 opportunities (each must cite at least "
            "one exact filename), and 2 to 4 coverage gaps. related_people and "
            "related_topics may be empty lists.\n\n" + "\n".join(lines)[:16000]
        )

        append_log(db, job_id, "Generating AI narrative...")
        update_job(db, job_id, progress=40.0)
        from tasks.analyze import _load_llm, _generate, _extract_json
        tokenizer, model = _load_llm()
        result = _extract_json(_generate(tokenizer, model, prompt, max_new_tokens=900))

        from topic_norm import normalize_topic_key, topic_label

        def person_refs(names) -> list[dict]:
            """Map LLM person names to ids where possible (case-insensitive)."""
            refs = []
            for n in names if isinstance(names, list) else []:
                name = str(n).strip()
                if not name:
                    continue
                refs.append({
                    "person_id": people_by_name.get(name.lower()),
                    "display_name": name[:200],
                })
            return refs[:6]

        def topic_refs(topics) -> list[dict]:
            refs = []
            for t in topics if isinstance(topics, list) else []:
                key = normalize_topic_key(str(t))
                if key:
                    refs.append({"key": key, "label": topic_label(key)})
            return refs[:6]

        headline = str(result.get("headline") or "")[:500] or None
        items = result.get("insights")
        cleaned = []
        if isinstance(items, list):
            for it in items[:8]:
                if isinstance(it, dict) and it.get("title") and it.get("detail"):
                    cleaned.append({
                        "title": str(it["title"])[:200],
                        "detail": str(it["detail"])[:1000],
                        "related_people": person_refs(it.get("related_people")),
                        "related_topics": topic_refs(it.get("related_topics")),
                    })

        opportunities = []
        for op in result.get("opportunities") if isinstance(result.get("opportunities"), list) else []:
            if not (isinstance(op, dict) and op.get("title") and op.get("rationale")):
                continue
            asset_ids, total_dur = [], 0.0
            for fn in op.get("asset_filenames") if isinstance(op.get("asset_filenames"), list) else []:
                hit = assets_by_filename.get(str(fn).strip().lower())
                if hit and hit[0] not in asset_ids:
                    asset_ids.append(hit[0])
                    total_dur += hit[1]
            if not asset_ids:
                continue  # opportunity must cite real footage
            opportunities.append({
                "title": str(op["title"])[:300],
                "rationale": str(op["rationale"])[:2000],
                "asset_ids": asset_ids[:10],
                "people": person_refs(op.get("people")),
                "total_duration_seconds": total_dur,
            })
        opportunities = opportunities[:4]

        coverage_gaps = []
        seen_keys = set()
        for g in result.get("coverage_gaps") if isinstance(result.get("coverage_gaps"), list) else []:
            key = normalize_topic_key(str(g))
            if key and key not in seen_keys:
                seen_keys.add(key)
                coverage_gaps.append({"key": key, "label": topic_label(key)})
        coverage_gaps = coverage_gaps[:6]

        db.execute(
            text("""
                INSERT INTO library_insights (id, headline, insights, opportunities, coverage_gaps, generated_at)
                VALUES (1, :headline, CAST(:insights AS jsonb), CAST(:opportunities AS jsonb), CAST(:coverage_gaps AS jsonb), :now)
                ON CONFLICT (id) DO UPDATE SET
                  headline = EXCLUDED.headline,
                  insights = EXCLUDED.insights,
                  opportunities = EXCLUDED.opportunities,
                  coverage_gaps = EXCLUDED.coverage_gaps,
                  generated_at = EXCLUDED.generated_at
            """),
            {
                "headline": headline,
                "insights": json.dumps(cleaned),
                "opportunities": json.dumps(opportunities),
                "coverage_gaps": json.dumps(coverage_gaps),
                "now": datetime.utcnow(),
            },
        )
        db.commit()

        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
        append_log(
            db, job_id,
            f"Insights generated: {len(cleaned)} findings, "
            f"{len(opportunities)} story opportunities, {len(coverage_gaps)} coverage gaps",
        )

    except Exception as e:
        db.rollback()
        update_job(db, job_id, status="error", error_message=str(e), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()
