"""AI media analysis: synopsis, key moments, and topics via the local LLM."""
import json
import re
from datetime import datetime
from app import celery_app
from db import get_session
from tasks.base import update_job, append_log
from config import LLM_MODEL

_CHUNK_CHARS = 20000  # ~6K tokens per chunk, well within the model's context

_llm = None  # (tokenizer, model) cached for the life of the worker process


# Shared persona: every AI automation should think like a creative, not a
# transcriptionist — hunting for emotional peaks, tension, transformation,
# memorable quotes and story potential, and being opinionated about it.
CREATIVE_PERSONA = (
    "You think like an award-winning creative editor and story producer. "
    "You hunt for emotional peaks, tension, transformation, conflict, humor, "
    "and quotable moments — not just literal topic descriptions. You notice "
    "what would move an audience, what earns its place in a cut, and what a "
    "producer could actually make from this footage. Be opinionated, vivid, "
    "and specific; never generic."
)


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


def _build_chunks(rows):
    """Split the full transcript into timecoded chunks of ~_CHUNK_CHARS each.

    Returns a list of (chunk_text, start_seconds, end_seconds). The whole
    transcript is always covered — nothing is truncated.
    """
    chunks = []
    parts = []
    total = 0
    chunk_start = float(rows[0][0])
    last_time = chunk_start
    for start, speaker, text_val in rows:
        t = float(start)
        line = f"[{_format_timecode(t)}] {speaker or 'Speaker'}: {text_val}"
        if total + len(line) > _CHUNK_CHARS and parts:
            chunks.append(("\n".join(parts), chunk_start, last_time))
            parts = []
            total = 0
            chunk_start = t
        parts.append(line)
        total += len(line)
        last_time = t
    if parts:
        chunks.append(("\n".join(parts), chunk_start, last_time))
    return chunks


def _generate(tokenizer, model, prompt: str, max_new_tokens: int = 1500) -> str:
    import torch
    messages = [{"role": "user", "content": prompt}]
    # enable_thinking=False: Qwen3 hybrid-reasoning models default to emitting
    # <think> blocks; disable for direct answers. Older templates ignore the kwarg.
    inputs = tokenizer.apply_chat_template(
        messages, add_generation_prompt=True, return_tensors="pt",
        enable_thinking=False,
    ).to(model.device)
    attention_mask = torch.ones_like(inputs)
    with torch.no_grad():
        output_ids = model.generate(
            inputs,
            attention_mask=attention_mask,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            temperature=None,
            top_p=None,
            top_k=None,
            pad_token_id=tokenizer.eos_token_id,
        )
    return tokenizer.decode(output_ids[0][inputs.shape[1]:], skip_special_tokens=True)


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
        chunks = _build_chunks(rows)

        append_log(db, job_id, f"Loading LLM: {LLM_MODEL}")
        update_job(db, job_id, progress=5.0)

        tokenizer, model = _load_llm()

        append_log(
            db, job_id,
            f"Analyzing full transcript in {len(chunks)} chunk(s) "
            f"(runtime ~{_format_timecode(duration)})",
        )

        # ── Map: analyze each chunk of the transcript ────────────────────────
        chunk_summaries = []
        all_moments = []
        all_topics = []
        for i, (chunk_text, c_start, c_end) in enumerate(chunks):
            prompt = (
                f"You are an expert media analyst. {CREATIVE_PERSONA}\n"
                "Below is a segment of a video "
                f"transcript covering {_format_timecode(c_start)} to {_format_timecode(c_end)} "
                f"of a {_format_timecode(duration)} video.\n\n"
                f"Transcript segment:\n{chunk_text}\n\n"
                "Respond with ONLY a JSON object, no other text, in exactly this shape:\n"
                "{\n"
                '  "summary": "detailed 3-5 sentence summary of what happens in this segment: '
                'the arguments made, who says what, and how the discussion develops",\n'
                '  "key_moments": [{"time": "MM:SS or HH:MM:SS", "title": "short title", '
                '"description": "one specific sentence about what is said or shown"}],\n'
                '  "topics": ["topic1", "topic2"]\n'
                "}\n\n"
                "Rules: 3-5 key moments for this segment, times must be timecodes that appear "
                "in this segment, 2-5 topics as short lowercase tags."
            )
            raw = _generate(tokenizer, model, prompt, max_new_tokens=1200)
            try:
                data = _extract_json(raw)
            except (ValueError, json.JSONDecodeError):
                append_log(db, job_id, f"Chunk {i + 1}/{len(chunks)}: unparseable LLM output, skipping")
                continue

            summary = str(data.get("summary", "")).strip()
            if summary:
                chunk_summaries.append(
                    f"[{_format_timecode(c_start)}–{_format_timecode(c_end)}] {summary}"
                )
            for km in (data.get("key_moments") or []):
                if not isinstance(km, dict):
                    continue
                title = str(km.get("title", "")).strip()
                if not title:
                    continue
                t = _timecode_to_seconds(km.get("time", c_start))
                # Clamp to this chunk's time range so hallucinated times stay plausible
                t = max(c_start, min(t, c_end if c_end > c_start else duration))
                all_moments.append({
                    "time": round(t, 1),
                    "title": title[:120],
                    "description": (str(km.get("description", "")).strip()[:300] or None),
                })
            all_topics.extend(
                str(t).strip().lower() for t in (data.get("topics") or []) if str(t).strip()
            )

            done = 5.0 + 75.0 * (i + 1) / len(chunks)
            update_job(db, job_id, progress=round(done, 1))
            append_log(db, job_id, f"Chunk {i + 1}/{len(chunks)} analyzed")

        if not chunk_summaries and not all_moments:
            raise RuntimeError("LLM returned no usable analysis for any transcript chunk")

        # ── Reduce: synthesize the overall analysis ──────────────────────────
        append_log(db, job_id, "Synthesizing overall analysis...")
        synopsis = None
        topics = []
        if chunk_summaries:
            # Cap synthesis input so very long media can't overflow the context
            _MAX_REDUCE_CHARS = 40000
            reduce_input = chunk_summaries
            if sum(len(s) for s in reduce_input) > _MAX_REDUCE_CHARS:
                reduce_input = [s[:1500] for s in reduce_input][:40]
            reduce_prompt = (
                f"You are an expert media analyst. {CREATIVE_PERSONA}\n"
                "Below are chronological segment summaries "
                f"of a single {_format_timecode(duration)} video.\n\n"
                + "\n\n".join(reduce_input)
                + "\n\nRespond with ONLY a JSON object, no other text, in exactly this shape:\n"
                "{\n"
                '  "synopsis": "one insightful paragraph (5-8 sentences) covering the full arc '
                'of the video: the central thesis, the main arguments and evidence presented, '
                'points of tension or contrast, and how it concludes",\n'
                '  "topics": ["topic1", "topic2"]\n'
                "}\n\n"
                "Rules: 4-8 topics as short lowercase tags capturing the main themes."
            )
            raw = _generate(tokenizer, model, reduce_prompt, max_new_tokens=1000)
            try:
                data = _extract_json(raw)
                synopsis = str(data.get("synopsis", "")).strip() or None
                topics = [
                    str(t).strip().lower() for t in (data.get("topics") or []) if str(t).strip()
                ]
            except (ValueError, json.JSONDecodeError):
                append_log(db, job_id, "Synthesis output unparseable, falling back to segment summaries")

        if not synopsis and chunk_summaries:
            synopsis = " ".join(s.split("] ", 1)[-1] for s in chunk_summaries)[:2000]
        if not topics:
            topics = list(dict.fromkeys(all_topics))
        topics = list(dict.fromkeys(topics))[:10]

        update_job(db, job_id, progress=90.0)

        # De-dupe moments that landed within 15s of each other with the same title
        all_moments.sort(key=lambda k: k["time"])
        key_moments = []
        for km in all_moments:
            if key_moments and km["title"].lower() == key_moments[-1]["title"].lower() \
                    and km["time"] - key_moments[-1]["time"] < 15:
                continue
            key_moments.append(km)
        # Keep a manageable number, evenly spread across the runtime
        _MAX_MOMENTS = 15
        if len(key_moments) > _MAX_MOMENTS:
            step = len(key_moments) / _MAX_MOMENTS
            key_moments = [key_moments[int(i * step)] for i in range(_MAX_MOMENTS)]

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

        # Chain the creative editor pass: story beats, clip suggestions,
        # editorial notes. Runs on the gpu queue so it can land on either card.
        # Guarded separately: analysis has already succeeded and been committed,
        # so a chaining failure must not flip this job back to error.
        try:
            from sqlalchemy import text
            already_active = db.execute(
                text("""
                    SELECT 1 FROM processing_jobs
                    WHERE media_id = :mid AND job_type = 'creative'
                      AND status IN ('pending', 'running')
                    LIMIT 1
                """),
                {"mid": media_id},
            ).fetchone()
            if not already_active:
                from tasks.base import create_job
                creative_job_id = create_job(db, media_id, "creative")
                from tasks.creative import creative_pass
                creative_pass.delay(media_id, creative_job_id)
        except Exception as chain_err:  # noqa: BLE001
            db.rollback()
            append_log(db, job_id, f"Could not queue creative pass: {chain_err}")

    except Exception as e:
        db.rollback()
        update_job(db, job_id, status="error", error_message=str(e), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()
