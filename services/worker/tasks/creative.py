"""Creative editor pass: story beats, clip suggestions, and editorial notes.

Thinks like a story editor over the full transcript: maps the narrative arc,
pulls the strongest soundbites as ready-to-cut clips with in/out points, and
writes per-video editorial notes (pacing, cuts, B-roll, best takes).
"""
import json
from datetime import datetime
from app import celery_app
from db import get_session
from tasks.base import update_job, append_log
from config import LLM_MODEL

_BEATS = {"hook", "setup", "development", "turn", "climax", "resolution"}
_NOTE_CATEGORIES = {"pacing", "structure", "cuts", "broll", "delivery", "best_take"}


def _clamp(value, lo: float, hi: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(v, hi))


@celery_app.task(bind=True, name="tasks.creative.creative_pass", queue="gpu")
def creative_pass(self, media_id: str, job_id: str):
    db = get_session()
    try:
        from sqlalchemy import text
        from tasks.analyze import (
            _load_llm, _generate, _extract_json, _build_chunks,
            _format_timecode, _timecode_to_seconds,
        )

        update_job(db, job_id, status="running", started_at=datetime.utcnow(),
                   celery_task_id=self.request.id)

        rows = db.execute(
            text("""
                SELECT start_time, speaker, text FROM transcript_segments
                WHERE media_id = :mid ORDER BY start_time
            """),
            {"mid": media_id},
        ).fetchall()
        if not rows:
            update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
            append_log(db, job_id, "No transcript available — skipping creative pass")
            return

        duration_row = db.execute(
            text("SELECT duration_seconds FROM media_assets WHERE id = :mid"),
            {"mid": media_id},
        ).fetchone()
        duration = float(duration_row[0]) if duration_row and duration_row[0] else float(rows[-1][0])

        chunks = _build_chunks(rows)
        append_log(db, job_id, f"Loading LLM: {LLM_MODEL}")
        update_job(db, job_id, progress=5.0)
        tokenizer, model = _load_llm()

        append_log(db, job_id, f"Creative pass over {len(chunks)} transcript chunk(s)")

        # ── Map: per-chunk soundbite mining ─────────────────────────────────
        all_clips = []
        chunk_notes = []
        for i, (chunk_text, c_start, c_end) in enumerate(chunks):
            prompt = (
                "You are a senior creative video editor reviewing raw footage. Below is "
                f"a transcript segment covering {_format_timecode(c_start)} to "
                f"{_format_timecode(c_end)} of a {_format_timecode(duration)} video.\n\n"
                f"Transcript segment:\n{chunk_text}\n\n"
                "Respond with ONLY a JSON object, no other text, in exactly this shape:\n"
                "{\n"
                '  "clips": [{"start": "MM:SS or HH:MM:SS", "end": "MM:SS or HH:MM:SS", '
                '"title": "short editorial title", "quote": "the strongest verbatim line", '
                '"reason": "one sentence: why an editor would pull this clip", '
                '"strength": 1-100, "platforms": ["youtube","tiktok","instagram","x"]}],\n'
                '  "segment_note": "one editor observation about this segment: pacing, '
                'energy, a great take, or what to cut"\n'
                "}\n\n"
                "Rules: pick only genuinely strong moments (0-4 clips for this segment). "
                "Each clip must be 8-45 seconds long, self-contained, and start/end at "
                "natural sentence boundaries. Times must be timecodes that appear in this "
                "segment. Score strength honestly — most footage is 40-70."
            )
            raw = _generate(tokenizer, model, prompt, max_new_tokens=1200)
            try:
                data = _extract_json(raw)
            except (ValueError, json.JSONDecodeError):
                append_log(db, job_id, f"Chunk {i + 1}/{len(chunks)}: unparseable LLM output, skipping")
                continue

            for c in (data.get("clips") or []):
                if not isinstance(c, dict) or not c.get("title") or not c.get("reason"):
                    continue
                start = _clamp(_timecode_to_seconds(c.get("start", c_start)), c_start, c_end or duration)
                end = _clamp(_timecode_to_seconds(c.get("end", start + 20)), start, duration)
                if end - start > 90:
                    end = start + 45.0
                end = min(end, duration)
                if end - start < 4.0:
                    # Too short to be a usable clip: extend forward, or if we're
                    # at the tail of the video, pull the in-point back instead.
                    end = min(start + 8.0, duration)
                    start = max(0.0, end - 8.0)
                if end - start < 4.0:
                    continue
                platforms = [
                    str(p).strip().lower() for p in (c.get("platforms") or [])
                    if str(p).strip()
                ][:4] or None
                strength = c.get("strength")
                try:
                    strength = int(_clamp(strength, 1, 100)) if strength is not None else None
                except (TypeError, ValueError):
                    strength = None
                all_clips.append({
                    "start": round(start, 1),
                    "end": round(end, 1),
                    "title": str(c["title"]).strip()[:120],
                    "quote": (str(c.get("quote", "")).strip()[:400] or None),
                    "reason": str(c["reason"]).strip()[:300],
                    "strength": strength,
                    "platforms": platforms,
                })
            note = str(data.get("segment_note", "")).strip()
            if note:
                chunk_notes.append(f"[{_format_timecode(c_start)}–{_format_timecode(c_end)}] {note}")

            update_job(db, job_id, progress=round(5.0 + 60.0 * (i + 1) / len(chunks), 1))
            append_log(db, job_id, f"Chunk {i + 1}/{len(chunks)} reviewed ({len(all_clips)} clips so far)")

        # ── Reduce: story arc + editorial notes over the whole piece ────────
        append_log(db, job_id, "Mapping story arc and writing editorial notes...")
        clip_lines = [
            f"- [{_format_timecode(c['start'])}–{_format_timecode(c['end'])}] "
            f"{c['title']} (strength {c.get('strength') or '?'}): {c['reason']}"
            for c in all_clips
        ]
        notes_input = "\n".join(chunk_notes)[:8000]
        clips_input = "\n".join(clip_lines)[:8000]

        synopsis_row = db.execute(
            text("SELECT synopsis FROM media_assets WHERE id = :mid"), {"mid": media_id}
        ).fetchone()
        synopsis = (synopsis_row[0] or "") if synopsis_row else ""

        reduce_prompt = (
            "You are a senior creative video editor delivering an edit review of a "
            f"{_format_timecode(duration)} video.\n\n"
            + (f"Synopsis: {synopsis[:1200]}\n\n" if synopsis else "")
            + f"Your segment-by-segment observations:\n{notes_input}\n\n"
            f"Strong clips you flagged:\n{clips_input}\n\n"
            "Respond with ONLY a JSON object, no other text, in exactly this shape:\n"
            "{\n"
            '  "logline": "one-sentence editorial pitch for this piece",\n'
            '  "story_beats": [{"time": "MM:SS or HH:MM:SS — the timecode where this beat '
            'happens, copied from the bracketed [start–end] ranges in the observations above", '
            '"beat": "hook|setup|development|turn|climax|resolution", '
            '"title": "short beat title", "description": "what happens and why it matters '
            'to the edit", "emotion": "dominant emotional register"}],\n'
            '  "editorial_notes": [{"category": '
            '"pacing|structure|cuts|broll|delivery|best_take", '
            '"note": "specific, actionable editing note"}]\n'
            "}\n\n"
            "Rules: 4-8 story beats in strictly increasing chronological order spanning the "
            "full runtime — every beat needs a distinct, real timecode taken from the "
            "observations, never 00:00 unless the beat truly opens the video; "
            "4-8 editorial notes an editor could act on today (what drags, what to cut, "
            "where B-roll is needed, which takes are strongest)."
        )
        raw = _generate(tokenizer, model, reduce_prompt, max_new_tokens=1400)
        update_job(db, job_id, progress=85.0)

        logline = None
        story_beats = []
        editorial_notes = []
        try:
            data = _extract_json(raw)
            logline = str(data.get("logline", "")).strip()[:300] or None
            for b in (data.get("story_beats") or []):
                if not isinstance(b, dict) or not b.get("title"):
                    continue
                beat = str(b.get("beat", "")).strip().lower()
                if beat not in _BEATS:
                    beat = "development"
                raw_time = next(
                    (b[k] for k in ("time", "timecode", "timestamp", "start", "at") if b.get(k) not in (None, "")),
                    0,
                )
                story_beats.append({
                    "time": round(_clamp(_timecode_to_seconds(raw_time), 0.0, duration), 1),
                    "beat": beat,
                    "title": str(b["title"]).strip()[:120],
                    "description": (str(b.get("description", "")).strip()[:400] or None),
                    "emotion": (str(b.get("emotion", "")).strip()[:60] or None),
                })
            for n in (data.get("editorial_notes") or []):
                if not isinstance(n, dict) or not n.get("note"):
                    continue
                cat = str(n.get("category", "")).strip().lower()
                if cat not in _NOTE_CATEGORIES:
                    cat = "structure"
                editorial_notes.append({
                    "category": cat,
                    "note": str(n["note"]).strip()[:500],
                })
        except (ValueError, json.JSONDecodeError):
            append_log(db, job_id, "Story-arc output unparseable — keeping clip suggestions only")

        # Repair degenerate arcs: if the model failed to give real timecodes
        # (all beats collapse to ~0:00 or a single timestamp), anchor them to
        # the flagged clips' times, or spread them across the runtime.
        if len(story_beats) >= 2:
            times = [b["time"] for b in story_beats]
            degenerate = max(times) - min(times) < max(2.0, duration * 0.02)
            if degenerate and duration > 0:
                anchors = sorted(c["start"] for c in all_clips)
                n = len(story_beats)
                if len(anchors) >= n:
                    idxs = [round(i * (len(anchors) - 1) / (n - 1)) for i in range(n)]
                    new_times = [anchors[j] for j in idxs]
                else:
                    new_times = [duration * i / n for i in range(n)]
                for b, t in zip(story_beats, new_times):
                    b["time"] = round(_clamp(float(t), 0.0, duration), 1)
                append_log(db, job_id,
                           "Story beat timecodes were missing/degenerate; re-anchored to clip times")

        story_beats.sort(key=lambda b: b["time"])
        story_beats = story_beats[:10]
        editorial_notes = editorial_notes[:10]

        # Rank clips: strength desc, dedupe overlapping windows
        all_clips.sort(key=lambda c: (-(c.get("strength") or 0), c["start"]))
        clips = []
        for c in all_clips:
            if any(not (c["end"] <= k["start"] or c["start"] >= k["end"]) for k in clips):
                continue
            clips.append(c)
            if len(clips) >= 12:
                break
        clips.sort(key=lambda c: c["start"])

        if not clips and not story_beats:
            raise RuntimeError("Creative pass produced no usable output")

        creative = {
            "logline": logline,
            "story_beats": story_beats,
            "clip_suggestions": clips,
            "editorial_notes": editorial_notes,
            "generated_at": datetime.utcnow().isoformat() + "Z",
        }
        db.execute(
            text("UPDATE media_assets SET creative = CAST(:c AS jsonb) WHERE id = :mid"),
            {"c": json.dumps(creative), "mid": media_id},
        )
        db.commit()

        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
        append_log(
            db, job_id,
            f"Creative pass complete: {len(story_beats)} beats, "
            f"{len(clips)} clip suggestions, {len(editorial_notes)} editorial notes",
        )

    except Exception as e:
        db.rollback()
        update_job(db, job_id, status="error", error_message=str(e), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()
