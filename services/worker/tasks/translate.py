"""Transcript translation into multiple languages via a local MT model.

Supports MADLAD-400 (default — Apache 2.0, target selected via a "<2xx> "
text prefix) and NLLB-200 (legacy — target selected via forced BOS token).
The engine is picked from the TRANSLATE_MODEL name.
"""
import json
import os
import re
import time
from datetime import datetime
from app import celery_app
from db import get_session
from tasks.base import update_job, append_log
from config import TRANSLATE_MODEL

# ISO code → NLLB-200 language code
NLLB_LANG_CODES = {
    "es": "spa_Latn",
    "fr": "fra_Latn",
    "de": "deu_Latn",
    "pt": "por_Latn",
    "it": "ita_Latn",
    "nl": "nld_Latn",
    "ru": "rus_Cyrl",
    "ja": "jpn_Jpan",
    "ko": "kor_Hang",
    "zh": "zho_Hans",
    "ar": "arb_Arab",
    "hi": "hin_Deva",
}

_BATCH_SIZE = 16
_translator = None

# Human-readable language names for LLM prompts.
LANG_NAMES = {
    "es": "Spanish", "fr": "French", "de": "German", "pt": "Portuguese",
    "it": "Italian", "nl": "Dutch", "ru": "Russian", "ja": "Japanese",
    "ko": "Korean", "zh": "Simplified Chinese", "ar": "Arabic", "hi": "Hindi",
}

# LLM path batch limits: small enough that the model can never run out of
# room and start summarizing, large enough for real conversational context.
_LLM_BATCH_MAX_SEGS = 40
_LLM_BATCH_MAX_CHARS = 6000
_GLOSSARY_CHUNK_CHARS = 9000
_GLOSSARY_MAX_TERMS = 60

# MADLAD-400 supports all our targets via "<2xx>" ISO-639-1 tags.
MADLAD_LANGS = set(NLLB_LANG_CODES.keys())


def _is_madlad() -> bool:
    return "madlad" in TRANSLATE_MODEL.lower()


def _load_translator():
    global _translator
    if _translator is None:
        import torch
        from huggingface_hub import snapshot_download
        from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
        # Download first via snapshot_download (thread-based, safe inside Celery's
        # daemonized prefork workers), then load from the local path. Loading a hub
        # repo id directly makes transformers spawn a safetensors auto-conversion
        # subprocess for legacy .bin checkpoints, which daemonic workers can't do
        # ("daemonic processes are not allowed to have children").
        local_dir = snapshot_download(TRANSLATE_MODEL)
        from tasks.gpu_mem import load_with_oom_retry

        def _load():
            if _is_madlad():
                tokenizer = AutoTokenizer.from_pretrained(local_dir)
            else:
                tokenizer = AutoTokenizer.from_pretrained(local_dir, src_lang="eng_Latn")
            model = AutoModelForSeq2SeqLM.from_pretrained(
                local_dir,
                torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
            )
            if torch.cuda.is_available():
                model = model.to("cuda")
            model.eval()
            return (tokenizer, model)

        _translator = load_with_oom_retry(TRANSLATE_MODEL, _load)
    return _translator


def _generate(tokenizer, model, texts: list[str], target: str, nllb_code: str) -> list[str]:
    import torch
    if _is_madlad():
        batch = [f"<2{target}> {t}" for t in texts]
        inputs = tokenizer(
            batch, return_tensors="pt", padding=True, truncation=True, max_length=512
        ).to(model.device)
        gen_kwargs = {}
    else:
        inputs = tokenizer(
            texts, return_tensors="pt", padding=True, truncation=True, max_length=512
        ).to(model.device)
        gen_kwargs = {"forced_bos_token_id": tokenizer.convert_tokens_to_ids(nllb_code)}
    with torch.no_grad():
        generated = model.generate(
            **inputs,
            max_new_tokens=256,
            num_beams=4,
            no_repeat_ngram_size=3,
            repetition_penalty=1.2,
            **gen_kwargs,
        )
    return tokenizer.batch_decode(generated, skip_special_tokens=True)


def _translate_batch(tokenizer, model, texts: list[str], target: str, nllb_code: str) -> list[str]:
    decoded = _generate(tokenizer, model, texts, target, nllb_code)
    results = []
    for src, out in zip(texts, decoded):
        cleaned = _clean_degeneration(src, out)
        # Degenerate outputs are usually a padded-batch artifact (short
        # segments batched with long ones). Retry the segment alone — this
        # fixes it far more often than any text cleanup can.
        if _is_degenerate(src, cleaned) and len(texts) > 1:
            solo = _clean_degeneration(src, _generate(tokenizer, model, [src], target, nllb_code)[0])
            if not _is_degenerate(src, solo) or len(solo) < len(cleaned):
                cleaned = solo
        results.append(cleaned)
    return results


# ---------------------------------------------------------------------------
# LLM-context translation path (remote LLM). Two-pass: a glossary pre-pass
# fixes names/terms once for the whole show, then conversation batches are
# translated with rolling context under a strict N-in/N-out contract — the
# contract is what makes summarization detectable and impossible to accept.
# MADLAD stays as the per-batch fallback, so a down LLM degrades quality, not
# availability.
# ---------------------------------------------------------------------------

def _parse_llm_json(raw: str):
    """Parse a JSON payload out of an LLM reply (tolerates code fences)."""
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.DOTALL).strip()
    start = cleaned.find("[") if cleaned.lstrip().startswith("[") or "[" in cleaned[:20] else cleaned.find("{")
    if start > 0:
        cleaned = cleaned[start:]
    return json.loads(cleaned)


def _llm_glossary(texts: list[str], target: str, log) -> dict:
    """Pass 1: extract proper nouns / recurring terms with one fixed translation
    each, so minute 80 uses the same names and terminology as minute 5."""
    from tasks.llm_remote import remote_chat
    lang_name = LANG_NAMES.get(target, target)
    glossary: dict = {}
    chunk: list[str] = []
    size = 0
    chunks: list[str] = []
    for t in texts:
        chunk.append(t)
        size += len(t) + 1
        if size >= _GLOSSARY_CHUNK_CHARS:
            chunks.append("\n".join(chunk))
            chunk, size = [], 0
    if chunk:
        chunks.append("\n".join(chunk))
    for ci, body in enumerate(chunks):
        try:
            reply = remote_chat([
                {"role": "system", "content": (
                    "You extract a translation glossary from a video transcript. "
                    f"Target language: {lang_name}. Return ONLY a JSON object mapping "
                    "source terms to their fixed translation. Include: person names, "
                    "place names, organization names, show/product titles, and recurring "
                    "domain terms. Names that should NOT be translated map to themselves. "
                    "At most 25 entries per reply. No commentary."
                )},
                {"role": "user", "content": body},
            ], max_new_tokens=800)
            data = _parse_llm_json(reply)
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip():
                        glossary.setdefault(k.strip(), v.strip())  # first-seen wins
        except Exception as e:
            log(f"Glossary pass chunk {ci + 1}/{len(chunks)} failed ({e}) — continuing without it")
        if len(glossary) >= _GLOSSARY_MAX_TERMS:
            break
    return dict(list(glossary.items())[:_GLOSSARY_MAX_TERMS])


def _llm_translate_lines(texts: list[str], target: str, glossary: dict, tail: list[str]) -> list[str]:
    """Translate one batch under the N-in/N-out contract. Raises on any
    violation (count mismatch, empty line) — the caller decides the fallback."""
    from tasks.llm_remote import remote_chat
    lang_name = LANG_NAMES.get(target, target)
    n = len(texts)
    glossary_block = ""
    if glossary:
        pairs = "\n".join(f"  {k} => {v}" for k, v in glossary.items())
        glossary_block = f"\nUse these fixed translations consistently:\n{pairs}\n"
    tail_block = ""
    if tail:
        tail_block = "\nThe previous lines were translated as (for continuity only, do not re-output):\n" + "\n".join(tail[-3:]) + "\n"
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
    reply = remote_chat([
        {"role": "system", "content": (
            f"You are a professional dubbing translator. Translate each numbered line "
            f"into {lang_name}. Rules: translate line-by-line — NEVER merge, drop, "
            f"summarize, or reorder lines; keep each translation about as long as the "
            f"source when spoken aloud (dubbing must fit the timing); preserve tone and "
            f"register; keep names untranslated unless the glossary says otherwise."
            f"{glossary_block}{tail_block}"
            f"Return ONLY a JSON array of exactly {n} strings, where item i is the "
            f"translation of line i. No commentary, no numbering inside the strings."
        )},
        {"role": "user", "content": numbered},
    ], max_new_tokens=max(1024, min(6000, sum(len(t) for t in texts) * 2)))
    data = _parse_llm_json(reply)
    if not isinstance(data, list) or len(data) != n:
        raise RuntimeError(f"LLM contract violation: {n} lines in, {len(data) if isinstance(data, list) else 'non-list'} out")
    out = []
    for i, item in enumerate(data):
        if not isinstance(item, str) or not item.strip():
            raise RuntimeError(f"LLM contract violation: empty translation at line {i + 1}")
        out.append(item.strip())
    return out


def _llm_translate_batch(texts: list[str], target: str, glossary: dict, tail: list[str]) -> list[str]:
    """Batch translation with a retry, then a split-in-half retry. Raises only
    when even single lines fail — the caller then falls back to MADLAD."""
    try:
        return _llm_translate_lines(texts, target, glossary, tail)
    except Exception:
        if len(texts) == 1:
            # One more direct attempt for a single line before giving up.
            return _llm_translate_lines(texts, target, glossary, tail)
        mid = len(texts) // 2
        left = _llm_translate_batch(texts[:mid], target, glossary, tail)
        right = _llm_translate_batch(texts[mid:], target, glossary, left)
        return left + right


def _plan_llm_batches(texts: list[str]) -> list[tuple[int, int]]:
    """(start, end) slices bounded by segment count and character budget.
    Limits are enforced BEFORE a line is added, so no batch exceeds them."""
    out: list[tuple[int, int]] = []
    start = 0
    size = 0
    for i, t in enumerate(texts):
        if i > start and (i - start >= _LLM_BATCH_MAX_SEGS or size + len(t) + 1 > _LLM_BATCH_MAX_CHARS):
            out.append((start, i))
            start, size = i, 0
        size += len(t) + 1
    if start < len(texts):
        out.append((start, len(texts)))
    return out


_ELLIPSIS_RE = re.compile(r"\.{4,}")


def _collapse_token_loops(value: str) -> str:
    """Collapse runs where a window of 1-4 whitespace tokens repeats 3+ times,
    e.g. '- Sí. - Sí. - Sí. - Sí.' -> '- Sí.' or '1.1 1.1 1.1 1.1' -> '1.1'."""
    toks = value.split()
    out: list[str] = []
    i, n = 0, len(toks)
    while i < n:
        collapsed = False
        for w in (1, 2, 3, 4):
            if i + 3 * w > n:
                break
            unit = toks[i:i + w]
            reps = 1
            while toks[i + reps * w:i + (reps + 1) * w] == unit:
                reps += 1
            if reps >= 3:
                out.extend(unit)
                i += reps * w
                collapsed = True
                break
        if not collapsed:
            out.append(toks[i])
            i += 1
    return " ".join(out)


def _clean_degeneration(source: str, out: str) -> str:
    """Strip repetition-loop artifacts the translation model sometimes emits."""
    cleaned = _ELLIPSIS_RE.sub("...", out)
    # Also collapse repeats glued together with no spaces, e.g. '1.1.1.1.1.'
    cleaned = re.sub(r"(\S{1,4})\1{3,}", r"\1", cleaned)
    cleaned = _collapse_token_loops(cleaned).strip()
    # If the output is still wildly longer than the source, it degenerated in a
    # way the collapse didn't catch — better truncated than garbled.
    if source and len(cleaned) > max(80, 4 * len(source)):
        cleaned = cleaned[: 4 * len(source)].rstrip()
    return cleaned


def _is_degenerate(source: str, cleaned: str) -> bool:
    """Heuristic: is this translation output still repetition-looped?"""
    if not cleaned:
        return True
    if source and len(cleaned) > max(80, 4 * len(source)):
        return True
    toks = cleaned.split()
    if len(toks) >= 8 and len(set(t.lower() for t in toks)) / len(toks) < 0.35:
        return True
    return False


@celery_app.task(bind=True, name="tasks.translate.translate_transcript", queue="gpu")
def translate_transcript(self, media_id: str, job_id: str, target_language: str):
    db = get_session()
    try:
        target = str(target_language).strip().lower()
        nllb_code = NLLB_LANG_CODES.get(target)
        if not nllb_code:
            raise RuntimeError(
                f"Unsupported language '{target}'. Supported: {', '.join(sorted(NLLB_LANG_CODES))}"
            )

        update_job(db, job_id, status="running", started_at=datetime.utcnow(),
                   celery_task_id=self.request.id, progress=0.0)

        from sqlalchemy import text
        all_rows = db.execute(
            text("""
                SELECT id, text, (translations ->> :lang) IS NOT NULL AS done
                FROM transcript_segments
                WHERE media_id = :mid ORDER BY start_time
            """),
            {"mid": media_id, "lang": target},
        ).fetchall()
        if not all_rows:
            raise RuntimeError("No transcript available — process the media first")

        # Resume: a partially translated job (crash/requeue) only translates
        # the missing segments. A fully translated asset re-translates
        # everything — that re-run is an explicit user request.
        done_count = sum(1 for r in all_rows if r[2])
        if 0 < done_count < len(all_rows):
            rows = [(r[0], r[1]) for r in all_rows if not r[2]]
            append_log(db, job_id, f"Resuming — {done_count} of {len(all_rows)} segments already translated")
        else:
            rows = [(r[0], r[1]) for r in all_rows]

        total = len(rows)
        last_report = time.monotonic()

        def _persist(batch_rows, translated):
            for row, tr in zip(batch_rows, translated):
                db.execute(
                    text("""
                        UPDATE transcript_segments
                        SET translations = COALESCE(translations, '{}'::jsonb) || CAST(:tr AS jsonb)
                        WHERE id = :sid
                    """),
                    {"tr": json.dumps({target: tr}), "sid": row[0]},
                )
            db.commit()

        from tasks.llm_remote import remote_enabled
        use_llm = remote_enabled() and os.getenv("TRANSLATE_USE_LLM", "1").lower() not in ("0", "false", "no")

        tokenizer = model = None

        def _madlad():
            nonlocal tokenizer, model
            if model is None:
                append_log(db, job_id, f"Loading translation model: {TRANSLATE_MODEL}")
                tokenizer, model = _load_translator()
            return tokenizer, model

        if use_llm:
            # Blank segments never go through the LLM contract (an empty line
            # would fail N-in/N-out validation and sink its whole batch) —
            # persist them as intentionally empty translations up front.
            blank_rows = [r for r in rows if not (r[1] or "").strip()]
            if blank_rows:
                _persist(blank_rows, [""] * len(blank_rows))
            rows = [r for r in rows if (r[1] or "").strip()]
            total = len(rows)
            if not total:
                raise RuntimeError("No non-empty transcript segments to translate")

            # Pass 1: translation bible (names/terms fixed once for the show).
            append_log(db, job_id, "Building glossary (names & recurring terms) via LLM")
            update_job(db, job_id, progress=2.0)
            glossary = _llm_glossary([r[1] for r in rows], target,
                                     lambda m: append_log(db, job_id, m))
            if glossary:
                append_log(db, job_id, f"Glossary: {len(glossary)} term(s) pinned")

            # Pass 2: conversation batches with rolling context.
            batches = _plan_llm_batches([r[1] for r in rows])
            append_log(db, job_id, f"Translating {total} segments to '{target}' via LLM in {len(batches)} batches")
            update_job(db, job_id, progress=5.0)
            tail: list[str] = []
            llm_failed_batches = 0
            for bi, (bs, be) in enumerate(batches):
                batch = rows[bs:be]
                texts = [r[1] for r in batch]
                try:
                    translated = _llm_translate_batch(texts, target, glossary, tail)
                except Exception as e:
                    llm_failed_batches += 1
                    append_log(db, job_id, f"LLM failed on batch {bi + 1}/{len(batches)} ({e}) — MADLAD fallback for this batch")
                    tk, md = _madlad()
                    translated = []
                    for ms in range(0, len(texts), _BATCH_SIZE):
                        translated.extend(_translate_batch(tk, md, texts[ms:ms + _BATCH_SIZE], target, nllb_code))
                _persist(batch, translated)
                tail = translated[-3:]

                now = time.monotonic()
                if now - last_report >= 3 or bi + 1 == len(batches):
                    update_job(db, job_id, progress=round(5.0 + 90.0 * (be / total), 1))
                    last_report = now
            if llm_failed_batches:
                append_log(db, job_id, f"{llm_failed_batches} batch(es) fell back to MADLAD")
        else:
            tk, md = _madlad()
            append_log(db, job_id, f"Translating {total} segments to '{target}'")
            update_job(db, job_id, progress=5.0)
            for start in range(0, total, _BATCH_SIZE):
                batch = rows[start:start + _BATCH_SIZE]
                translated = _translate_batch(
                    tk, md, [r[1] for r in batch], target, nllb_code
                )
                _persist(batch, translated)

                now = time.monotonic()
                if now - last_report >= 3 or start + _BATCH_SIZE >= total:
                    progress = 5.0 + 90.0 * min(1.0, (start + len(batch)) / total)
                    update_job(db, job_id, progress=round(progress, 1))
                    last_report = now

        db.execute(
            text("""
                UPDATE media_assets
                SET translated_languages = (
                    SELECT jsonb_agg(DISTINCT lang)
                    FROM jsonb_array_elements_text(
                        COALESCE(translated_languages, '[]'::jsonb) || CAST(:lang AS jsonb)
                    ) AS lang
                )
                WHERE id = :mid
            """),
            {"lang": json.dumps([target]), "mid": media_id},
        )
        db.commit()

        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
        append_log(db, job_id, f"Translated {total} segments to '{target}'")

    except Exception as e:
        db.rollback()
        update_job(db, job_id, status="error", error_message=str(e), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()
