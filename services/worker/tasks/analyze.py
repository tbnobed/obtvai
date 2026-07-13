"""AI media analysis: synopsis, key moments, and topics via the local LLM."""
import json
import re
from datetime import datetime
from app import celery_app
from db import get_session
from tasks.base import update_job, append_log
from config import LLM_MODEL

_MAX_TRANSCRIPT_CHARS = 24000

_llm = None  # (tokenizer, model) cached for the life of the worker process


def _load_llm():
    global _llm
    if _llm is None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(LLM_MODEL)
        model = AutoModelForCausalLM.from_pretrained(
            LLM_MODEL,
            torch_dtype=torch.float16,
            device_map="auto",
        )
        _llm = (tokenizer, model)
    return _llm


def _format_timecode(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _build_transcript_text(rows) -> str:
    parts = []
    total = 0
    for start, speaker, text_val in rows:
        line = f"[{_format_timecode(float(start))}] {speaker or 'Speaker'}: {text_val}"
        total += len(line)
        if total > _MAX_TRANSCRIPT_CHARS:
            parts.append("[... transcript truncated ...]")
            break
        parts.append(line)
    return "\n".join(parts)


def _extract_json(raw: str) -> dict:
    """Pull the first JSON object out of LLM output (may be wrapped in prose/fences)."""
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    candidate = fence.group(1) if fence else None
    if candidate is None:
        brace = raw.find("{")
        if brace == -1:
            raise ValueError("No JSON object in LLM output")
        depth = 0
        for i, ch in enumerate(raw[brace:], start=brace):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = raw[brace:i + 1]
                    break
        if candidate is None:
            raise ValueError("Unbalanced JSON in LLM output")
    return json.loads(candidate)


def _timecode_to_seconds(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    parts = str(value).strip().split(":")
    try:
        parts_f = [float(p) for p in parts]
    except ValueError:
        return 0.0
    seconds = 0.0
    for p in parts_f:
        seconds = seconds * 60 + p
    return seconds


@celery_app.task(bind=True, name="tasks.analyze.analyze_media", queue="gpu")
def analyze_media(self, media_id: str, job_id: str):
    db = get_session()
    try:
        update_job(db, job_id, status="running", started_at=datetime.utcnow(), celery_task_id=self.request.id)

        from sqlalchemy import text
        rows = db.execute(
            text("""
                SELECT start_time, speaker, text FROM transcript_segments
                WHERE media_id = :mid ORDER BY start_time
            """),
            {"mid": media_id},
        ).fetchall()

        if not rows:
            update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
            append_log(db, job_id, "No transcript available — skipping analysis")
            return

        duration = float(rows[-1][0])
        transcript_text = _build_transcript_text(rows)

        append_log(db, job_id, f"Loading LLM: {LLM_MODEL}")
        update_job(db, job_id, progress=10.0)

        import torch
        tokenizer, model = _load_llm()

        append_log(db, job_id, "Generating analysis...")
        update_job(db, job_id, progress=40.0)

        prompt = (
            "You are an expert media analyst reviewing a video transcript with timecodes.\n\n"
            f"Transcript:\n{transcript_text}\n\n"
            "Respond with ONLY a JSON object, no other text, in exactly this shape:\n"
            "{\n"
            '  "synopsis": "2-4 sentence summary of the content",\n'
            '  "key_moments": [{"time": "MM:SS", "title": "short title", "description": "one sentence"}],\n'
            '  "topics": ["topic1", "topic2"]\n'
            "}\n\n"
            "Rules: 5-10 key moments spread across the full runtime, times must match "
            "transcript timecodes, 3-8 topics as short lowercase tags."
        )

        messages = [{"role": "user", "content": prompt}]
        inputs = tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, return_tensors="pt"
        ).to(model.device)
        with torch.no_grad():
            output_ids = model.generate(
                inputs,
                max_new_tokens=1500,
                do_sample=False,
                pad_token_id=tokenizer.eos_token_id,
            )
        raw = tokenizer.decode(output_ids[0][inputs.shape[1]:], skip_special_tokens=True)

        update_job(db, job_id, progress=80.0)
        data = _extract_json(raw)

        synopsis = str(data.get("synopsis", "")).strip() or None
        topics = [str(t).strip() for t in (data.get("topics") or []) if str(t).strip()][:10]

        key_moments = []
        for km in (data.get("key_moments") or [])[:12]:
            if not isinstance(km, dict):
                continue
            title = str(km.get("title", "")).strip()
            if not title:
                continue
            t = _timecode_to_seconds(km.get("time", 0))
            if duration > 0:
                t = min(t, duration)
            key_moments.append({
                "time": round(t, 1),
                "title": title[:120],
                "description": (str(km.get("description", "")).strip()[:300] or None),
            })
        key_moments.sort(key=lambda k: k["time"])

        if not synopsis and not key_moments:
            raise RuntimeError(f"LLM returned no usable analysis: {raw[:300]}")

        db.execute(
            text("""
                UPDATE media_assets
                SET synopsis = :synopsis,
                    key_moments = CAST(:key_moments AS jsonb),
                    topics = CAST(:topics AS jsonb)
                WHERE id = :mid
            """),
            {
                "synopsis": synopsis,
                "key_moments": json.dumps(key_moments),
                "topics": json.dumps(topics),
                "mid": media_id,
            },
        )
        db.commit()
        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
        append_log(db, job_id, f"Analysis complete: {len(key_moments)} key moments, {len(topics)} topics")

    except Exception as e:
        db.rollback()
        update_job(db, job_id, status="error", error_message=str(e), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()
