"""Generate CLIP visual embeddings for each scene thumbnail and store in Qdrant."""
import os
import uuid
from datetime import datetime
from app import celery_app
from db import get_session
from tasks.base import update_job, append_log, update_asset
from config import THUMBNAILS_DIR, QDRANT_URL, EMBEDDINGS_MODEL, VISION_MODEL


@celery_app.task(bind=True, name="tasks.visual_embed.embed_scenes", queue="gpu")
def embed_scenes(self, media_id: str, job_id: str):
    db = get_session()
    try:
        update_job(db, job_id, status="running", started_at=datetime.utcnow(), celery_task_id=self.request.id)
        update_asset(db, media_id, processing_stage="visual_embed", processing_progress=82.0)

        from sqlalchemy import text
        scenes = db.execute(
            text("SELECT id, thumbnail_url, start_time, end_time FROM scenes WHERE media_id = :mid"),
            {"mid": media_id},
        ).fetchall()
        vrow = db.execute(
            text("SELECT original_path, proxy_path FROM media_assets WHERE id = :mid"),
            {"mid": media_id},
        ).fetchone()
        video_path = (vrow[1] or vrow[0]) if vrow else None
        if video_path and not os.path.exists(video_path):
            video_path = None

        if not scenes:
            update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
            append_log(db, job_id, "No scenes to embed")
            return

        import torch
        from transformers import AutoProcessor, AutoModel
        from PIL import Image
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams, PointStruct

        device = "cuda" if torch.cuda.is_available() else "cpu"
        append_log(db, job_id, f"Loading vision model {VISION_MODEL} on {device}...")
        # AutoModel handles both CLIP and SigLIP/SigLIP-2 checkpoints; both
        # expose get_image_features / get_text_features in a shared space.
        from tasks.gpu_mem import load_with_oom_retry
        model = load_with_oom_retry(
            VISION_MODEL,
            lambda: AutoModel.from_pretrained(VISION_MODEL).to(device).eval(),
        )
        processor = AutoProcessor.from_pretrained(VISION_MODEL)

        from tasks.qdrant_util import get_qdrant, qdrant_retry
        qdrant = get_qdrant()
        _ensure_collection(qdrant, "scenes", _vector_dim(model))

        # Idempotent retry: remove points from any previous run for this asset
        # so re-detected scenes don't leave orphaned vectors behind.
        from qdrant_client.models import Filter, FieldCondition, MatchValue, FilterSelector
        try:
            qdrant.delete(
                collection_name="scenes",
                points_selector=FilterSelector(filter=Filter(must=[
                    FieldCondition(key="media_id", match=MatchValue(value=media_id)),
                ])),
            )
        except Exception as e:
            append_log(db, job_id, f"Stale point cleanup skipped: {e}")

        import subprocess
        import tempfile
        import numpy as np

        def _is_blackish(img) -> bool:
            arr = np.asarray(img.resize((64, 64)))
            return bool(arr.mean() < 10 or arr.std() < 5)

        def _embed_and_upsert(img, point_id: str, payload: dict) -> bool:
            inputs = processor(images=img, return_tensors="pt").to(device)
            with torch.no_grad():
                feats = model.get_image_features(**inputs)
            vec = feats[0].cpu().numpy()
            vec = (vec / (vec ** 2).sum() ** 0.5).tolist()
            qdrant_retry(
                qdrant.upsert,
                collection_name="scenes",
                points=[PointStruct(id=point_id, vector=vec, payload=payload)],
            )
            return True

        embedded = 0
        attempted = 0
        skipped_black = 0
        frame_points = 0
        for scene_id, thumb_url, start_sec, end_sec in scenes:
            duration = max(0.0, float(end_sec or 0) - float(start_sec or 0))
            scene_ok = False
            try:
                # 1) The representative thumbnail (kept as the scene's primary
                # vector — same deterministic ID as before).
                if thumb_url:
                    thumb_file = os.path.join(THUMBNAILS_DIR, os.path.basename(thumb_url))
                    if os.path.exists(thumb_file):
                        attempted += 1
                        img = Image.open(thumb_file).convert("RGB")
                        # Near-black/uniform frames (fades, textless-master
                        # gaps) embed as noise and poison visual search.
                        if _is_blackish(img):
                            skipped_black += 1
                            attempted -= 1
                        else:
                            _embed_and_upsert(
                                img,
                                str(uuid.uuid5(uuid.NAMESPACE_DNS, scene_id)),
                                {"scene_id": scene_id, "media_id": media_id},
                            )
                            embedded += 1
                            scene_ok = True

                # 2) Dense sampling: one keyframe cannot represent a long or
                # busy scene (concerts, award shows). Sample extra frames
                # every ~6s (max 10 per scene) and index one vector each —
                # search merges them back to the best score per scene.
                if video_path and duration > 6.0:
                    step = max(6.0, duration / 10.0)
                    t = float(start_sec) + step / 2.0
                    while t < float(end_sec) - 1.0:
                        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
                            frame_path = tf.name
                        try:
                            proc = subprocess.run(
                                ["ffmpeg", "-y", "-ss", str(t), "-i", video_path,
                                 "-vframes", "1", "-q:v", "4", frame_path],
                                capture_output=True, timeout=60,
                            )
                            if proc.returncode == 0 and os.path.getsize(frame_path) > 0:
                                fimg = Image.open(frame_path).convert("RGB")
                                if not _is_blackish(fimg):
                                    _embed_and_upsert(
                                        fimg,
                                        str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{scene_id}@{t:.1f}")),
                                        {"scene_id": scene_id, "media_id": media_id,
                                         "frame_time": round(t, 2)},
                                    )
                                    frame_points += 1
                                    scene_ok = True
                        finally:
                            try:
                                os.unlink(frame_path)
                            except OSError:
                                pass
                        t += step

                if scene_ok:
                    db.execute(
                        text("UPDATE scenes SET embedding_id = :eid WHERE id = :sid"),
                        {"eid": scene_id, "sid": scene_id},
                    )
            except Exception as e:
                append_log(db, job_id, f"Scene {scene_id} embed failed: {e}")

        db.commit()
        if attempted > 0 and embedded == 0 and frame_points == 0:
            raise RuntimeError(
                f"All {attempted} scene embeddings failed — check logs above (likely a "
                f"Qdrant dimension mismatch or model load failure)"
            )
        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
        update_asset(db, media_id, processing_stage="visual_embed_complete", processing_progress=90.0)
        append_log(
            db, job_id,
            f"Embedded {embedded} scene thumbnails + {frame_points} sampled frames "
            f"({skipped_black} near-black skipped)"
        )

    except Exception as e:
        db.rollback()
        update_job(db, job_id, status="error", error_message=str(e), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()


def _vector_dim(model) -> int:
    """Output dim of get_image_features: CLIP has a projection head,
    SigLIP/SigLIP-2 embed at the tower hidden size."""
    cfg = model.config
    dim = getattr(cfg, "projection_dim", None)
    if dim:
        return int(dim)
    return int(cfg.text_config.hidden_size)


def _ensure_collection(qdrant, name: str, size: int):
    from qdrant_client.models import Distance, VectorParams
    try:
        info = qdrant.get_collection(name)
        if info.config.params.vectors.size != size:
            qdrant.delete_collection(name)
            qdrant.create_collection(name, vectors_config=VectorParams(size=size, distance=Distance.COSINE))
    except Exception:
        qdrant.create_collection(name, vectors_config=VectorParams(size=size, distance=Distance.COSINE))
