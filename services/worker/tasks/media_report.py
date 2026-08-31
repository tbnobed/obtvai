"""On-demand, transcript-backed CSV report generation for selected media."""
import csv
import io
import json
import os
import re
from datetime import datetime

from app import celery_app
from db import get_session
from tasks.base import append_log, update_job


_SYNOPSIS_WORDS = 500
_MAX_REDUCE_CHARS = 18000
_REPORT_INGEST_URL = "https://reair.obtv.io/api/reports/ingest"
_REPORT_HEADERS = [
    "ClipID",
    "Air Dates",
    "Host",
    "Guests",
    "Short Synopsis",
    "Long Synopsis",
    "Any dates mentioned (timecode where)",
    "Any date sensitive material (timecode where)",
]


def _safe_error(exc: Exception) -> str:
    """Keep a remote-provider URL or token from being persisted in a job error."""
    message = str(exc)
    message = re.sub(
        r"(?i)(api[_-]?key|token|authorization)=([^&\s]+)",
        r"\1=[REDACTED]",
        message,
    )
    return message[:1000]


def _report_air_dates(row: dict) -> str:
    def label(kind: str, value) -> str | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return f"{kind}: {value:%Y-%m-%d}"
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return f"{kind}: {parsed:%Y-%m-%d}"
        except ValueError:
            return f"{kind}: {value}"

    return " | ".join(
        value
        for value in (
            label("Original", row.get("curator_original_air_date")),
            label("Last", row.get("curator_last_air_date")),
        )
        if value
    )


def _render_report_csv(rows: list[dict]) -> str:
    """Return the exact UTF-8-BOM CSV text used for posting and downloads."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=_REPORT_HEADERS,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        if not isinstance(row, dict):
            continue
        writer.writerow({
            "ClipID": row.get("clip_id") or "",
            "Air Dates": _report_air_dates(row),
            "Host": row.get("host") or "",
            "Guests": row.get("guests") or "",
            "Short Synopsis": row.get("short_synopsis") or "",
            "Long Synopsis": row.get("long_synopsis") or "",
            "Any dates mentioned (timecode where)": row.get("date_mentions") or "",
            "Any date sensitive material (timecode where)": row.get("date_sensitive") or "",
        })
    return "\ufeff" + output.getvalue()


def _post_report(name: str, content: str) -> dict:
    """Post once; blind retries could duplicate a report after an ambiguous timeout."""
    import httpx

    api_key = os.getenv("REPORT_INGEST_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("REPORT_INGEST_API_KEY is not configured")
    ingest_url = os.getenv("REPORT_INGEST_URL", _REPORT_INGEST_URL).strip() or _REPORT_INGEST_URL
    try:
        response = httpx.post(
            ingest_url,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"name": name, "content": content},
            timeout=30.0,
        )
        if response.status_code != 201:
            detail = re.sub(r"\s+", " ", response.text).strip()
            detail = detail.replace(api_key, "[REDACTED]")[:500]
            raise RuntimeError(
                f"re-air ingest returned HTTP {response.status_code}"
                + (f": {detail}" if detail else "")
            )
        payload = response.json()
    except httpx.HTTPError as exc:
        error = _safe_error(exc).replace(api_key, "[REDACTED]")
        raise RuntimeError(f"re-air ingest request failed: {error}") from exc
    except ValueError as exc:
        raise RuntimeError("re-air ingest returned invalid JSON") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("re-air ingest returned an invalid response")
    required = ("id", "name", "clipCount", "uploadedAt")
    missing = [key for key in required if payload.get(key) is None]
    if missing:
        raise RuntimeError(
            f"re-air ingest response omitted: {', '.join(missing)}"
        )
    return {
        "id": str(payload["id"]),
        "name": str(payload["name"]),
        "clip_count": int(payload["clipCount"]),
        "uploaded_at": str(payload["uploadedAt"]),
    }


def _limit_words(value: str, limit: int = _SYNOPSIS_WORDS) -> str:
    words = re.findall(r"\S+", value.strip())
    return " ".join(words[:limit])


def _word_count(value: str) -> int:
    return len(re.findall(r"\S+", value.strip()))


def _clean_prose(value: str) -> str:
    """Normalize a prose-only LLM response without treating it as JSON."""
    text = str(value or "").strip()
    text = re.sub(r"^```(?:text|markdown)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    text = re.sub(
        r"^(?:long|short)\s+synopsis\s*:\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", text).strip()


def _generate_json(
    tokenizer,
    model,
    prompt: str,
    *,
    max_new_tokens: int,
    required_keys: tuple[str, ...],
    attempts: int = 3,
) -> dict:
    """Retry malformed local-LLM JSON instead of discarding the whole asset."""
    from tasks.analyze import _extract_json, _generate

    last_error: Exception | None = None
    for attempt in range(attempts):
        retry_instruction = ""
        if attempt:
            retry_instruction = (
                "\n\nIMPORTANT: The previous response was not valid complete JSON. "
                "Return exactly one complete JSON object with no markdown, commentary, "
                "or text before or after it. Keep string values concise enough to finish."
            )
        try:
            parsed = _extract_json(
                _generate(
                    tokenizer,
                    model,
                    prompt + retry_instruction,
                    max_new_tokens=max_new_tokens,
                )
            )
            missing = [key for key in required_keys if not parsed.get(key)]
            if missing:
                raise ValueError(
                    f"LLM JSON omitted required field(s): {', '.join(missing)}"
                )
            return parsed
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc

    raise RuntimeError(
        f"LLM did not return valid report JSON after {attempts} attempts: "
        f"{_safe_error(last_error or RuntimeError('unknown JSON error'))}"
    )


def _clip_id(asset: dict) -> str:
    """Derive the facility ClipID without exposing an OBTV UUID or Curator GUID."""
    for raw_path in (
        asset.get("curator_web_proxy_path"),
        asset.get("original_path"),
    ):
        path = str(raw_path or "").strip().replace("\\", "/").rstrip("/")
        if not path:
            continue
        name = path.rsplit("/", 1)[-1]
        if name.casefold().endswith("_video.mp4"):
            return name[: -len("_video.mp4")]
        if "." not in name:
            return name
    return ""


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
              AND (
                :publish_status <> 'pending'
                OR COALESCE(params->>'publish_status', 'pending') = 'pending'
              )
        """),
        {
            "params": json.dumps(params),
            "publish_status": params.get("publish_status") or "pending",
            "now": datetime.utcnow(),
            "job_id": job_id,
        },
    )
    db.commit()


def _claim_report_publish(db, job_id: str, params: dict) -> bool:
    """Atomically reserve the report's only external publish attempt."""
    from sqlalchemy import text

    claimed = db.execute(
        text("""
            UPDATE processing_jobs
            SET params = CAST(:params AS jsonb), heartbeat_at = :now
            WHERE id = :job_id
              AND status = 'running'
              AND COALESCE(params->>'publish_status', 'pending') = 'pending'
            RETURNING id
        """),
        {"params": json.dumps(params), "now": datetime.utcnow(), "job_id": job_id},
    ).first()
    db.commit()
    return claimed is not None


def _post_report_if_running(db, job_id: str, name: str, content: str) -> dict | None:
    """Last cancellation check before irreversible external ingestion."""
    from sqlalchemy import text

    status = db.execute(
        text("SELECT status FROM processing_jobs WHERE id = :job_id"),
        {"job_id": job_id},
    ).scalar_one_or_none()
    if status != "running":
        return None
    return _post_report(name, content)


def _reduce_summaries(tokenizer, model, summaries: list[str]) -> str:
    """Fit chronological evidence into the prompt budget without discarding detail."""
    from tasks.analyze import _generate

    pending = [summary for summary in summaries if summary.strip()]
    if not pending:
        return ""

    # Most programs produce only a few chunk summaries. Keep those summaries
    # intact: collapsing them into one short paragraph leaves too little factual
    # material for the required 500-word synopsis.
    while sum(len(item) for item in pending) > _MAX_REDUCE_CHARS:
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
        if len(reduced) == len(pending):
            break
        pending = reduced

    return "\n".join(pending)


def _make_fallback_row(asset: dict) -> dict:
    def serialize_date(value):
        return value.isoformat() if hasattr(value, "isoformat") else value

    return {
        "media_id": asset["id"],
        "filename": asset["filename"],
        "clip_id": _clip_id(asset),
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
    from tasks.analyze import _build_chunks, _format_timecode, _generate

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
        parsed = _generate_json(
            tokenizer,
            model,
            prompt,
            max_new_tokens=1800,
            required_keys=("summary",),
        )
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
    long_prompt = (
        "Using only the chronological evidence below, write a complete factual synopsis "
        "of at least 550 words. Develop the chronology, themes, arguments, examples, and "
        "conclusions without repetition, generic filler, or invented facts. Return only "
        "the synopsis prose with no heading, JSON, markdown, or commentary.\n\n"
        f"Chronological evidence:\n{reduced}"
    )
    long_synopsis = _clean_prose(
        _generate(tokenizer, model, long_prompt, max_new_tokens=2200)
    )

    # If generation stops early, request only the missing continuation. Rewriting
    # the entire draft repeatedly proved both less reliable and more prone to
    # malformed JSON than extending the existing factual prose.
    for attempt in range(3):
        current_words = _word_count(long_synopsis)
        if current_words >= _SYNOPSIS_WORDS:
            break
        needed = _SYNOPSIS_WORDS - current_words
        continuation_prompt = (
            f"Continue the synopsis draft with at least {needed + 40} additional words "
            "using only factual details from the chronological evidence. Add relevant "
            "details not already covered in the draft. Do not repeat sentences, add "
            "generic filler, invent facts, summarize the instructions, or restart the "
            "synopsis. Return only the continuation prose with no heading, JSON, markdown, "
            "or commentary.\n\n"
            f"Chronological evidence:\n{reduced}\n\nExisting draft:\n{long_synopsis}"
        )
        continuation = _clean_prose(
            _generate(tokenizer, model, continuation_prompt, max_new_tokens=1000)
        )
        if continuation:
            long_synopsis = f"{long_synopsis} {continuation}".strip()
        append_log(
            db,
            job_id,
            f"{asset['filename']}: long synopsis continuation {attempt + 1}/3 "
            f"produced {_word_count(long_synopsis)}/{_SYNOPSIS_WORDS} words",
        )

    if _word_count(long_synopsis) < _SYNOPSIS_WORDS:
        raise RuntimeError(
            f"Long synopsis did not reach the required {_SYNOPSIS_WORDS} words"
        )
    long_synopsis = _limit_words(long_synopsis, _SYNOPSIS_WORDS)
    short_prompt = (
        "Using only the synopsis below, write a clear factual short synopsis in one or "
        "two sentences. Return only the short synopsis with no heading, JSON, markdown, "
        "or commentary.\n\n"
        f"Synopsis:\n{long_synopsis}"
    )
    short_synopsis = _clean_prose(
        _generate(tokenizer, model, short_prompt, max_new_tokens=220)
    )[:1200]
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

        # Never repeat an external attempt for this report. If a worker vanished
        # while the state was "posting", the remote outcome is ambiguous.
        prior_publish_status = params.get("publish_status")
        if isinstance(params.get("csv_content"), str) and prior_publish_status in {
            "posting", "success", "error",
        }:
            if prior_publish_status == "posting":
                params["publish_status"] = "error"
                params["publish_error"] = (
                    "The previous automatic post outcome is unknown after worker interruption; "
                    "it was not retried to avoid a duplicate report."
                )
                _store_report_state(db, job_id, params)
                append_log(db, job_id, params["publish_error"])
            update_job(
                db,
                job_id,
                status="success",
                progress=100.0,
                finished_at=datetime.utcnow(),
            )
            return

        assets = db.execute(
            text("""
                SELECT id, filename, original_path, curator_web_proxy_path, synopsis,
                       curator_original_air_date, curator_last_air_date
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
                append_log(
                    db,
                    job_id,
                    f"{asset['filename']}: report analysis failed ({error}); "
                    "exported available metadata",
                )
            params["rows"].append(row)
            _store_report_state(db, job_id, params)
            progress = round(100.0 * (index + 1) / len(media_ids), 1)
            update_job(db, job_id, progress=progress)
            append_log(db, job_id, f"{asset['filename']}: report row {index + 1}/{len(media_ids)} complete")

        failure_count = len(params["failures"])
        finished_at = datetime.utcnow()
        csv_name = f"reair-report-{finished_at:%Y%m%d-%H%M%S}.csv"
        csv_content = _render_report_csv(params["rows"])
        params.update({
            "csv_name": csv_name,
            "csv_content": csv_content,
            "publish_status": "posting",
            "publish_error": None,
            "published_report": None,
        })
        if not _claim_report_publish(db, job_id, params):
            append_log(
                db,
                job_id,
                "Skipped duplicate automatic post attempt for this Re-Air Report",
            )
            return
        append_log(db, job_id, f"Posting {csv_name} to re-air management")
        try:
            published = _post_report_if_running(
                db,
                job_id,
                csv_name,
                csv_content,
            )
            if published is None:
                append_log(
                    db,
                    job_id,
                    "Automatic re-air post skipped because the report was cancelled",
                )
                return
            params["publish_status"] = "success"
            params["published_report"] = published
            append_log(
                db,
                job_id,
                f"Posted to re-air management as report {published['id']} "
                f"({published['clip_count']} clips)",
            )
        except Exception as exc:
            error = _safe_error(exc)
            params["publish_status"] = "error"
            params["publish_error"] = error
            append_log(db, job_id, f"Automatic re-air post failed ({error})")
        _store_report_state(db, job_id, params)
        update_job(
            db,
            job_id,
            status="success",
            progress=100.0,
            finished_at=finished_at,
        )
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