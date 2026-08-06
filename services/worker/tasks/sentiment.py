"""Per-segment sentiment & emotion pass.

Scores every transcript segment with a sentiment value (-1..1) and a
dominant emotion label so editors can see the emotional shape of a video
on the timeline and search the library by emotion.
"""
import json
from datetime import datetime
from app import celery_app
from db import get_session
from tasks.base import update_job, append_log
from config import LLM_MODEL

# Fixed vocabulary keeps labels searchable/filterable instead of free-form.
EMOTIONS = [
    "neutral", "joy", "humor", "excitement", "warmth", "pride",
    "sadness", "anger", "tension", "fear", "surprise",
]
_EMOTION_SET = set(EMOTIONS)

_BATCH = 40  # max segments per LLM call
_LINE_CAP = 300  # chars per transcript line in the prompt (long ASR runs get truncated)
_BATCH_CHAR_BUDGET = 8000  # max total prompt chars from transcript lines per batch


def _clamp(v) -> float | None:
    try:
        return max(-1.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return None


@celery_app.task(bind=True, name="tasks.sentiment.sentiment_pass", queue="gpu")
def sentiment_pass(self, media_id: str, job_id: str):
    db = get_session()
    try:
        from sqlalchemy import text
        from tasks.analyze import _load_llm, _generate, _extract_json

        update_job(db, job_id, status="running", started_at=datetime.utcnow(),
                   celery_task_id=self.request.id)

        rows = db.execute(
            text("""
                SELECT id, start_time, speaker, text FROM transcript_segments
                WHERE media_id = :mid ORDER BY start_time
            """),
            {"mid": media_id},
        ).fetchall()
        if not rows:
            update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
            append_log(db, job_id, "No transcript — skipping sentiment pass")
            return

        append_log(db, job_id, f"Loading LLM: {LLM_MODEL}")
        update_job(db, job_id, progress=3.0)
        tokenizer, model = _load_llm()

        # Batch by both count and character budget so a run of long ASR
        # segments can't overflow the model context or starve the JSON reply.
        batches: list[list] = []
        cur: list = []
        cur_chars = 0
        for r in rows:
            line_len = min(len(r[3] or ""), _LINE_CAP) + 8
            if cur and (len(cur) >= _BATCH or cur_chars + line_len > _BATCH_CHAR_BUDGET):
                batches.append(cur)
                cur = []
                cur_chars = 0
            cur.append(r)
            cur_chars += line_len
        if cur:
            batches.append(cur)
        append_log(db, job_id, f"Scoring {len(rows)} segments in {len(batches)} batch(es)")

        scored = 0
        for bi, batch in enumerate(batches):
            lines = "\n".join(
                f"{i + 1}. {(r[3] or '')[:_LINE_CAP]}" for i, r in enumerate(batch)
            )
            prompt = (
                "You are an emotion analyst for a video editing team. For each "
                "numbered transcript line below, rate the emotional charge of the "
                "SPEAKER's delivery/content.\n\n"
                f"Lines:\n{lines}\n\n"
                "Respond with ONLY a JSON object, no other text, exactly:\n"
                '{"items": [{"n": <line number>, "s": <sentiment -1.0 (very negative) '
                'to 1.0 (very positive), 0 = neutral>, "e": "<one of: '
                + ", ".join(EMOTIONS) + '>"}]}\n'
                "Include every line number exactly once."
            )
            try:
                parsed = _extract_json(_generate(tokenizer, model, prompt, max_new_tokens=1800))
                items = parsed.get("items") or []
            except Exception as gen_err:  # noqa: BLE001
                append_log(db, job_id, f"Batch {bi + 1}: LLM parse failed ({gen_err}); segments left unscored")
                items = []
            by_n = {}
            for it in items:
                try:
                    n = int(it.get("n"))
                except (TypeError, ValueError):
                    continue
                if 1 <= n <= len(batch):
                    by_n[n] = it
            for i, r in enumerate(batch):
                it = by_n.get(i + 1)
                if not it:
                    continue
                s = _clamp(it.get("s"))
                e = str(it.get("e", "")).strip().lower()
                if e not in _EMOTION_SET:
                    e = None
                if s is None and e is None:
                    continue
                db.execute(
                    text("""
                        UPDATE transcript_segments
                        SET sentiment = :s, emotion = :e
                        WHERE id = :sid
                    """),
                    {"s": s, "e": e, "sid": r[0]},
                )
                scored += 1
            db.commit()
            update_job(db, job_id, progress=5.0 + 93.0 * (bi + 1) / len(batches))

        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
        append_log(db, job_id, f"Sentiment pass complete: {scored}/{len(rows)} segments scored")

    except Exception as e:
        db.rollback()
        update_job(db, job_id, status="error", error_message=str(e), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()
