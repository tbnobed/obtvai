"""Transcript translation into multiple languages via a local MT model.

Supports MADLAD-400 (default — Apache 2.0, target selected via a "<2xx> "
text prefix) and NLLB-200 (legacy — target selected via forced BOS token).
The engine is picked from the TRANSLATE_MODEL name.
"""
import json
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
        _translator = (tokenizer, model)
    return _translator


def _translate_batch(tokenizer, model, texts: list[str], target: str, nllb_code: str) -> list[str]:
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
            max_new_tokens=512,
            num_beams=4,
            no_repeat_ngram_size=4,
            **gen_kwargs,
        )
    decoded = tokenizer.batch_decode(generated, skip_special_tokens=True)
    return [_clean_degeneration(src, out) for src, out in zip(texts, decoded)]


_ELLIPSIS_RE = re.compile(r"\.{4,}")
# A short chunk (1-8 chars, optionally followed by space/comma) repeated 3+
# times back-to-back, e.g. "1.1.1.1.1." or "no no no no no".
_LOOP_RE = re.compile(r"(\S{1,8}[ ,]?)(?:\1){3,}")


def _clean_degeneration(source: str, out: str) -> str:
    """Strip repetition-loop artifacts the translation model sometimes emits."""
    cleaned = _ELLIPSIS_RE.sub("...", out)
    for _ in range(5):
        collapsed = _LOOP_RE.sub(r"\1", cleaned)
        if collapsed == cleaned:
            break
        cleaned = collapsed
    cleaned = cleaned.strip()
    # If the output is still wildly longer than the source, it degenerated in a
    # way the regexes didn't catch — better to keep it truncated than garbled.
    if source and len(cleaned) > max(80, 4 * len(source)):
        cleaned = cleaned[: 4 * len(source)].rstrip()
    return cleaned


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
        rows = db.execute(
            text("""
                SELECT id, text FROM transcript_segments
                WHERE media_id = :mid ORDER BY start_time
            """),
            {"mid": media_id},
        ).fetchall()
        if not rows:
            raise RuntimeError("No transcript available — process the media first")

        append_log(db, job_id, f"Loading translation model: {TRANSLATE_MODEL}")
        update_job(db, job_id, progress=5.0)
        tokenizer, model = _load_translator()

        append_log(db, job_id, f"Translating {len(rows)} segments to '{target}'")
        total = len(rows)
        last_report = time.monotonic()

        for start in range(0, total, _BATCH_SIZE):
            batch = rows[start:start + _BATCH_SIZE]
            translated = _translate_batch(
                tokenizer, model, [r[1] for r in batch], target, nllb_code
            )
            for row, tr in zip(batch, translated):
                db.execute(
                    text("""
                        UPDATE transcript_segments
                        SET translations = COALESCE(translations, '{}'::jsonb) || CAST(:tr AS jsonb)
                        WHERE id = :sid
                    """),
                    {"tr": json.dumps({target: tr}), "sid": row[0]},
                )
            db.commit()

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
