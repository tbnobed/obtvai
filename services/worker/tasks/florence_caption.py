"""Fast scene captioning with Microsoft Florence-2 Large.

Florence runs locally on the GPU worker and captions scene thumbnails in
micro-batches.  It is the library-scale default; BAGEL remains available as a
slower, manually selected high-detail caption stage.
"""

import logging
import os
from datetime import datetime

from app import celery_app
from config import THUMBNAILS_DIR
from db import get_session
from tasks.base import append_log, update_job

logger = logging.getLogger("tasks.florence_caption")

_MODEL_ID = os.environ.get("FLORENCE_CAPTION_MODEL", "microsoft/Florence-2-large")
_BATCH_SIZE = max(1, int(os.environ.get("FLORENCE_CAPTION_BATCH_SIZE", "4")))
_MAX_NEW_TOKENS = max(8, int(os.environ.get("FLORENCE_CAPTION_MAX_TOKENS", "64")))
_TASK_PROMPT = os.environ.get("FLORENCE_CAPTION_TASK", "<DETAILED_CAPTION>")

# Registered with tasks.gpu_mem so the shared GPU is released after idle time.
_florence_cache: dict = {}


def _load_florence():
    cached = _florence_cache.get("model")
    if cached is not None:
        return (
            cached,
            _florence_cache["processor"],
            _florence_cache["device"],
            _florence_cache["dtype"],
        )

    import torch
    from transformers import AutoModelForCausalLM, AutoProcessor

    if not torch.cuda.is_available():
        raise RuntimeError("Florence-2 bulk captioning requires a CUDA GPU worker")

    device = "cuda"
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16

    def _loader():
        processor = AutoProcessor.from_pretrained(_MODEL_ID, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(
            _MODEL_ID,
            trust_remote_code=True,
            torch_dtype=dtype,
            attn_implementation="sdpa",
        ).to(device).eval()
        return model, processor

    from tasks.gpu_mem import load_with_oom_retry

    model, processor = load_with_oom_retry(_MODEL_ID, _loader)
    _florence_cache.update(
        model=model,
        processor=processor,
        device=device,
        dtype=dtype,
    )
    return model, processor, device, dtype


def _parsed_caption(parsed) -> str | None:
    """Normalize Florence processor output into one compact string."""
    value = parsed.get(_TASK_PROMPT) if isinstance(parsed, dict) else parsed
    if isinstance(value, dict):
        value = value.get("caption") or value.get("text")
    if isinstance(value, list):
        value = " ".join(str(part) for part in value)
    caption = " ".join(str(value or "").split()).strip()
    return caption or None


def _caption_images(images) -> list[str | None]:
    import torch

    model, processor, device, dtype = _load_florence()
    prompts = [_TASK_PROMPT] * len(images)
    inputs = processor(
        text=prompts,
        images=images,
        return_tensors="pt",
        padding=True,
    )
    model_inputs = {}
    for key, value in inputs.items():
        if not hasattr(value, "to"):
            model_inputs[key] = value
        elif value.is_floating_point():
            model_inputs[key] = value.to(device=device, dtype=dtype)
        else:
            model_inputs[key] = value.to(device=device)

    with torch.inference_mode():
        generated_ids = model.generate(
            **model_inputs,
            max_new_tokens=_MAX_NEW_TOKENS,
            num_beams=1,
            do_sample=False,
            use_cache=True,
        )

    generated_texts = processor.batch_decode(
        generated_ids,
        skip_special_tokens=False,
    )
    captions = []
    for generated_text, image in zip(generated_texts, images):
        parsed = processor.post_process_generation(
            generated_text,
            task=_TASK_PROMPT,
            image_size=image.size,
        )
        captions.append(_parsed_caption(parsed))
    return captions


def _caption_images_resilient(images) -> list[str | None]:
    """Caption a batch, splitting it when shared-GPU pressure causes OOM."""
    oom_message = None
    try:
        return _caption_images(images)
    except Exception as exc:
        from tasks.gpu_mem import is_cuda_oom

        if not is_cuda_oom(exc):
            raise
        oom_message = str(exc)

    # Run recovery outside the except block so the failed traceback does not
    # retain model tensors. Drop all long-lived GPU models before retrying.
    from tasks.gpu_mem import release_gpu_models

    released = release_gpu_models()
    if len(images) == 1:
        logger.warning(
            "Florence CUDA OOM on one image; released %s and retrying once: %s",
            ", ".join(released) or "CUDA cache",
            oom_message,
        )
        return _caption_images(images)

    midpoint = len(images) // 2
    logger.warning(
        "Florence CUDA OOM on batch of %d; released %s and splitting into %d + %d",
        len(images),
        ", ".join(released) or "CUDA cache",
        midpoint,
        len(images) - midpoint,
    )
    return (
        _caption_images_resilient(images[:midpoint])
        + _caption_images_resilient(images[midpoint:])
    )


@celery_app.task(
    bind=True,
    name="tasks.florence_caption.caption_scenes",
    queue="gpu",
)
def caption_scenes(self, media_id: str, job_id: str):
    db = get_session()
    try:
        from PIL import Image
        from sqlalchemy import text

        update_job(
            db,
            job_id,
            status="running",
            started_at=datetime.utcnow(),
            celery_task_id=self.request.id,
        )

        scenes = db.execute(
            text("""
                SELECT id, thumbnail_url
                FROM scenes
                WHERE media_id = :mid
                  AND thumbnail_url IS NOT NULL
                  AND (description IS NULL OR description = '')
                ORDER BY start_time
            """),
            {"mid": media_id},
        ).fetchall()

        if not scenes:
            append_log(db, job_id, "All scenes already captioned — nothing to do")
            update_job(
                db,
                job_id,
                status="success",
                finished_at=datetime.utcnow(),
                progress=100.0,
            )
            return

        total = len(scenes)
        append_log(
            db,
            job_id,
            f"Captioning {total} scenes with Florence-2 Large "
            f"(batch size {_BATCH_SIZE})",
        )
        captioned = 0
        attempted = 0
        missing = 0
        empty = 0
        preserved = 0
        generated = 0

        for offset in range(0, total, _BATCH_SIZE):
            current_status = db.execute(
                text("SELECT status FROM processing_jobs WHERE id = :jid"),
                {"jid": job_id},
            ).scalar()
            if current_status in ("cancelled", "error"):
                append_log(db, job_id, f"Captioning stopped with status {current_status}")
                return

            batch_rows = scenes[offset:offset + _BATCH_SIZE]
            valid_rows = []
            images = []
            for scene_id, thumb_url in batch_rows:
                thumb_path = os.path.join(
                    THUMBNAILS_DIR,
                    os.path.basename(thumb_url),
                )
                if not os.path.exists(thumb_path):
                    missing += 1
                    continue
                try:
                    with Image.open(thumb_path) as image:
                        images.append(image.convert("RGB").copy())
                    valid_rows.append((scene_id, thumb_path))
                except Exception as exc:
                    missing += 1
                    logger.warning("Could not load scene thumbnail %s: %s", thumb_path, exc)

            if images:
                captions = _caption_images_resilient(images)
                for (scene_id, _), caption in zip(valid_rows, captions):
                    if not caption:
                        empty += 1
                        continue
                    generated += 1
                    result = db.execute(
                        text("""
                            UPDATE scenes
                            SET description = :desc
                            WHERE id = :sid
                              AND (description IS NULL OR description = '')
                        """),
                        {"desc": caption, "sid": scene_id},
                    )
                    if (result.rowcount or 0) > 0:
                        captioned += 1
                    else:
                        preserved += 1
                # Preserve completed batches if a later batch is cancelled or
                # fails. Reruns skip these descriptions.
                db.commit()

            attempted += len(batch_rows)
            progress = min(99.0, 100.0 * attempted / total)
            update_job(db, job_id, progress=progress)
            self.update_state(
                state="PROGRESS",
                meta={
                    "attempted": attempted,
                    "captioned": captioned,
                    "total": total,
                    "batch_size": _BATCH_SIZE,
                },
            )
            if attempted % max(20, _BATCH_SIZE) == 0 or attempted == total:
                append_log(
                    db,
                    job_id,
                    f"Processed {attempted}/{total} scenes "
                    f"({captioned} captions)",
                )

        if generated == 0 and total > missing:
            raise RuntimeError(
                f"Florence-2 returned no usable captions for {total - missing} readable thumbnails"
            )

        append_log(
            db,
            job_id,
            f"Captioned {captioned}/{total} scenes with Florence-2 Large"
            + (
                f" ({missing} thumbnails missing or unreadable, {empty} empty captions, "
                f"{preserved} existing descriptions preserved)"
                if missing or empty or preserved
                else ""
            ),
        )
        update_job(
            db,
            job_id,
            status="success",
            finished_at=datetime.utcnow(),
            progress=100.0,
        )

    except Exception as exc:
        db.rollback()
        update_job(
            db,
            job_id,
            status="error",
            error_message=str(exc),
            finished_at=datetime.utcnow(),
        )
        raise
    finally:
        db.close()