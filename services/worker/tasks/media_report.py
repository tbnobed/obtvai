"""On-demand, transcript-backed CSV report generation for selected media."""
import json
import re
from datetime import datetime

from app import celery_app
from db import get_session
from tasks.base import append_log, update_job


_SYNOPSIS_WORDS = 500
_MAX_REDUCE_CHARS = 18000


def _safe_error(exc: Exception) -> str:
    """Keep a remote-provider URL or token from being persisted in a job error."""
    message = str(exc)
    message = re.sub(
        r"(?i)(api[_-]?key|token|authorization)=([^&\s]+)",
        r"\1=[REDACTED]",
        message,
    )
    return message[:1000]


def _limit_words(value: str, limit: int = _SYNOPSIS_WORDS) -> str:
    words = re.findall(r"\S+", value.strip())
    return " ".join(words[:limit])


def _word_count(value: str) -> int:
    return len(re.findall(r"\S+", value.strip()))


def _unique_names(values) -> list[str]:
    out, seen = [], set()
    for raw in values if isinstance(values, list) else []:
        name = re.sub(r"\s+", " ", str(raw or "")).strip()
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            out.append(name[:160])
    return out


def _format_evidence(items, chunk_start: float, chunk_end: float, duration: float) -> list[dict]:
    from tasks.analyze import _format_timecode, _timecode_to_seconds

    out, seen = [], set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        detail = re.sub(r"\s+", " ", str(item.get("detail") or "")).strip()
        if not detail:
            continue
        seconds = _timecode_to_seconds(item.get("timecode", chunk_start))
        seconds = max(chunk_start, min(seconds, chunk_end if chunk_end > chunk_start else duration))
        timecode = _format_timecode(seconds)
        key = (timecode, detail.casefold())
        if key not in seen:
            seen.add(key)
            out.append({"timecode": timecode, "detail": detail[:500]})
    return out


def _evidence_text(items: list[dict]) -> str:
    unique, seen = [], set()
    for item in items:
        key = (item["timecode"], item["detail"].casefold())
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return "\n".join(f"{item['timecode']} — {item['detail']}" for item in unique)


def _store_report_state(db, job_id: str, params: dict) -> None:
    """JSONB needs an explicit cast when binding serialized JSON through text()."""
    from sqlalchemy import text

    db.execute(
        text("""
            UPDATE processing_jobs
            SET params = CAST(:params AS jsonb), heartbeat_at = :now
            WHERE id = :job_id
        """),
        {"params": json.dumps(params), "now": datetime.utcnow(), "job_id": job_id},
    )
    db.commit()


def _reduce_summaries(tokenizer, model, summaries: list[str]) -> str:
    """Consolidate every chronological chunk without truncating unseen tail chunks."""
    from tasks.analyze import _generate

    pending = [summary for summary in summaries if summary.strip()]
    if not pending:
        return ""

    while len(pending) > 1 or sum(len(item) for item in pending) > _MAX_REDUCE_CHARS:
        groups, group, size = [], [], 0
        for item in pending:
            if group and size + len(item) > _MAX_REDUCE_CHARS:
                groups.append(group)
                group, size = [], 0
            group.append(item)
            size += len(item)
        if group:
            groups.append(group)

        reduced = []
        for group in groups:
            prompt = (
                "Condense these chronological transcript summaries into a faithful "
                "chronological account. Preserve at least one concrete point from every "
                "time range; do not add facts. Plain text only.\n\n"
                + "\n".join(group)
            )
            result = _generate(tokenizer, model, prompt, max_new_tokens=1000).strip()
            reduced.append(result or "\n".join(group))
        if len(reduced) >= len(pending) and len(pending) == 1:
            break
        pending = reduced

    return pending[0]


def _make_fallback_row(asset: dict) -> dict:
    def serialize_date(value):
        return value.isoformat() if hasattr(value, "isoformat") else value

    return {
        "media_id": asset["id"],
        "filename": asset["filename"],
        "curator_original_air_date": serialize_date(asset.get("curator_original_air_date")),
        "curator_last_air_date": serialize_date(asset.get("curator_last_air_date")),
        "host": "",
        "guests": "",
        "short_synopsis": (asset.get("synopsis") or "")[:1200],
        "long_synopsis": _limit_words(asset.get("synopsis") or ""),
        "date_mentions": "",
        "date_sensitive": "",
    }


def _analyze_asset(
    db, job_id: str, asset: dict, tokenizer, model, progress_start: float, progress_span: float,
) -> dict:
    """Generate one report row; raises only when the asset cannot be analyzed."""
    from sqlalchemy import text
    from tasks.analyze import _build_chunks, _extract_json, _format_timecode, _generate

    rows = db.execute(
        text("""
            SELECT start_time, speaker, text
            FROM transcript_segments
            WHERE media_id = :media_id
            ORDER BY start_time
        """),
        {"media_id": asset["id"]},
    ).fetchall()
    if not rows:
        append_log(db, job_id, f"{asset['filename']}: no transcript; exported available metadata")
        row = _make_fallback_row(asset)
        row["_partial_reason"] = "No transcript available; exported metadata only"
        return row

    name_rows = db.execute(
        text("""
            SELECT pa.speaker_label, p.display_name
            FROM person_appearances pa
            JOIN people p ON p.id = pa.person_id
            WHERE pa.media_id = :media_id AND pa.speaker_label IS NOT NULL
        """),
        {"media_id": asset["id"]},
    ).fetchall()
    speaker_names = {label: name for label, name in name_rows if label and name}
    duration = float(rows[-1][0])
    chunks = _build_chunks(rows, speaker_names)
    chunk_summaries, hosts, guests, date_mentions, date_sensitive = [], [], [], [], []

    for index, (chunk_text, chunk_start, chunk_end) in enumerate(chunks):
        prompt = (
            "You are preparing a factual media-library report from a transcript. "
            "Only use the supplied transcript. Do not guess names or dates. "
            f"This excerpt covers {_format_timecode(chunk_start)} to "
            f"{_format_timecode(chunk_end)} of a {_format_timecode(duration)} recording.\n\n"
            f"Transcript:\n{chunk_text}\n\n"
            "Return ONLY this JSON object:\n"
            "{\n"
            '  "summary": "A concise factual summary of this excerpt",\n'
            '  "hosts": ["names explicitly established as host/interviewer/presenter"],\n'
            '  "guests": ["names explicitly established as guest/interview subject"],\n'
            '  "date_mentions": [{"timecode": "MM:SS or HH:MM:SS", "detail": "date or time reference and context"}],\n'
            '  "date_sensitive": [{"timecode": "MM:SS or HH:MM:SS", "detail": "time-sensitive claim, deadline, upcoming/past event, relative-date reference, or expiring/current information and context"}]\n'
            "}\n"
            "Rules: lists may be empty. Every evidence timecode must appear in this excerpt. "
            "Include explicit calendar dates and meaningful relative-date references."
        )
        parsed = _extract_json(_generate(tokenizer, model, prompt, max_new_tokens=1200))
        summary = re.sub(r"\s+", " ", str(parsed.get("summary") or "")).strip()
        if summary:
            chunk_summaries.append(
                f"[{_format_timecode(chunk_start)}–{_format_timecode(chunk_end)}] {summary[:1200]}"
            )
        hosts.extend(_unique_names(parsed.get("hosts")))
        guests.extend(_unique_names(parsed.get("guests")))
        date_mentions.extend(_format_evidence(parsed.get("date_mentions"), chunk_start, chunk_end, duration))
        date_sensitive.extend(_format_evidence(parsed.get("date_sensitive"), chunk_start, chunk_end, duration))
        update_job(
            db,
            job_id,
            progress=round(progress_start + progress_span * 0.85 * (index + 1) / len(chunks), 1),
        )
        append_log(db, job_id, f"{asset['filename']}: transcript chunk {index + 1}/{len(chunks)} analyzed")

    if not chunk_summaries:
        raise RuntimeError("The report analysis returned no usable transcript summaries")

    reduced = _reduce_summaries(tokenizer, model, chunk_summaries)
    synthesis_prompt = (
        "Using only this chronological evidence, produce JSON with a clear short synopsis "
        "(1-2 sentences) and a complete long synopsis of exactly 500 words. Develop the "
        "chronology, themes, arguments, examples, and conclusions in sufficient detail to "
        "reach exactly 500 words without repetition or invented facts. Return JSON only.\n\n"
        + reduced
        + '\n\n{"short_synopsis": "...", "long_synopsis": "..."}'
    )
    synthesis = _extract_json(_generate(tokenizer, model, synthesis_prompt, max_new_tokens=1800))
    long_synopsis = re.sub(
        r"\s+", " ", str(synthesis.get("long_synopsis") or "")
    ).strip()
    short_synopsis = re.sub(
        r"\s+", " ", str(synthesis.get("short_synopsis") or "")
    ).strip()[:1200]

    # Models often stop a little short even when given an exact word target.
    # Give them two factual rewrite attempts before treating the row as partial;
    # accepting a short result would silently violate the report contract.
    for _ in range(2):
        current_words = _word_count(long_synopsis)
        if current_words >= _SYNOPSIS_WORDS:
            break
        repair_prompt = (
            f"The draft below is {current_words} words. Rewrite it as exactly "
            f"{_SYNOPSIS_WORDS} words using only the supplied chronological evidence. "
            "Expand factual context, chronology, themes, examples, and conclusions. "
            "Do not repeat sentences, add generic filler, or invent facts. "
            'Return only JSON in the form {"long_synopsis": "..."}.\n\n'
            f"Chronological evidence:\n{reduced}\n\nDraft:\n{long_synopsis}"
        )
        repaired = _extract_json(
            _generate(tokenizer, model, repair_prompt, max_new_tokens=1800)
        )
        long_synopsis = re.sub(
            r"\s+", " ", str(repaired.get("long_synopsis") or "")
        ).strip()

    if _word_count(long_synopsis) < _SYNOPSIS_WORDS:
        raise RuntimeError(
            f"Long synopsis did not reach the required {_SYNOPSIS_WORDS} words"
        )
    long_synopsis = _limit_words(long_synopsis, _SYNOPSIS_WORDS)
    if not short_synopsis:
        short_synopsis = long_synopsis[:1200]

    # A person cannot be both fields in one report unless the transcript explicitly
    # introduces separate roles; favor the host classification in ambiguous output.
    host_names = _unique_names(hosts)
    host_keys = {name.casefold() for name in host_names}
    guest_names = [name for name in _unique_names(guests) if name.casefold() not in host_keys]
    row = _make_fallback_row(asset)
    row.update({
        "host": "; ".join(host_names),
        "guests": "; ".join(guest_names),
        "short_synopsis": short_synopsis,
        "long_synopsis": long_synopsis,
        "date_mentions": _evidence_text(date_mentions),
        "date_sensitive": _evidence_text(date_sensitive),
    })
    return row


@celery_app.task(bind=True, name="tasks.media_report.generate_media_report", queue="gpu")
def generate_media_report(self, job_id: str, media_id: str | None = None):
    """Build report rows sequentially so a selection has coherent progress."""
    db = get_session()
    try:
        from sqlalchemy import text
        from tasks.analyze import _load_llm

        state = db.execute(
            text("SELECT params FROM processing_jobs WHERE id = :job_id"),
            {"job_id": job_id},
        ).mappings().first()
        params = dict(state["params"] or {}) if state else {}
        media_ids = [str(item) for item in params.get("media_ids", []) if str(item)]
        if not media_ids:
            raise RuntimeError("Re-Air Report has no selected assets")

        assets = db.execute(
            text("""
                SELECT id, filename, synopsis, curator_original_air_date, curator_last_air_date
                FROM media_assets
                WHERE id = ANY(:media_ids)
            """),
            {"media_ids": media_ids},
        ).mappings().all()
        by_id = {row["id"]: dict(row) for row in assets}
        missing = [asset_id for asset_id in media_ids if asset_id not in by_id]
        if missing:
            raise RuntimeError(f"Selected assets are no longer available: {', '.join(missing[:5])}")

        update_job(
            db, job_id, status="running", progress=0.0, started_at=datetime.utcnow(),
            celery_task_id=self.request.id,
        )
        append_log(db, job_id, f"Generating Re-Air Report for {len(media_ids)} asset(s)")
        tokenizer, model = _load_llm()

        params["rows"] = []
        params["failures"] = []
        for index, asset_id in enumerate(media_ids):
            asset = by_id[asset_id]
            progress_start = 100.0 * index / len(media_ids)
            progress_span = 100.0 / len(media_ids)
            try:
                row = _analyze_asset(
                    db, job_id, asset, tokenizer, model, progress_start, progress_span,
                )
                partial_reason = row.pop("_partial_reason", None)
                if partial_reason:
                    params["failures"].append({
                        "media_id": asset_id,
                        "filename": asset["filename"],
                        "error": partial_reason,
                    })
            except Exception as exc:
                error = _safe_error(exc)
                row = _make_fallback_row(asset)
                params["failures"].append({"media_id": asset_id, "filename": asset["filename"], "error": error})
                append_log(db, job_id, f"{asset['filename']}: report analysis failed; exported available metadata")
            params["rows"].append(row)
            _store_report_state(db, job_id, params)
            progress = round(100.0 * (index + 1) / len(media_ids), 1)
            update_job(db, job_id, progress=progress)
            append_log(db, job_id, f"{asset['filename']}: report row {index + 1}/{len(media_ids)} complete")

        failure_count = len(params["failures"])
        update_job(db, job_id, status="success", progress=100.0, finished_at=datetime.utcnow())
        append_log(
            db, job_id,
            f"Re-Air Report complete: {len(params['rows'])} row(s), {failure_count} partial result(s)",
        )
    except Exception as exc:
        db.rollback()
        update_job(
            db, job_id, status="error", error_message=_safe_error(exc),
            finished_at=datetime.utcnow(),
        )
        raise
    finally:
        db.close()