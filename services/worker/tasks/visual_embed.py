"""Generate CLIP visual embeddings for each scene thumbnail and store in Qdrant."""
import os
import uuid
from datetime import datetime
from ..app import celery_app
from ..db import get_session
from .base import update_job, append_log, update_asset
from ..config import THUMBNAILS_DIR, QDRANT_URL, EMBEDDINGS_MODEL, VISION_MODEL


@celery_app.task(bind=True, name="tasks.visual_embed.embed_scenes", queue="gpu")
def embed_scenes(self, media_id: str, job_id: str):
    db = get_session()
    try:
        update_job(db, job_id, status="running", started_at=datetime.utcnow(), celery_task_id=self.request.id)
        update_asset(db, media_id, processing_stage="visual_embed", processing_progress=82.0)

        from sqlalchemy import text
        scenes = db.execute(
            text("SELECT id, thumbnail_url FROM scenes WHERE media_id = :mid"),
            {"mid": media_id},
        ).fetchall()

        if not scenes:
            update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
            append_log(db, job_id, "No scenes to embed")
            return

        import torch
        from transformers import CLIPProcessor, CLIPModel
        from PIL import Image
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams, PointStruct

        device = "cuda" if torch.cuda.is_available() else "cpu"
        append_log(db, job_id, f"Loading CLIP model on {device}...")
        model = CLIPModel.from_pretrained(VISION_MODEL).to(device)
        processor = CLIPProcessor.from_pretrained(VISION_MODEL)

        qdrant = QdrantClient(url=QDRANT_URL)
        _ensure_collection(qdrant, "scenes", model.config.projection_dim)

        embedded = 0
        attempted = 0
        for scene_id, thumb_url in scenes:
            if not thumb_url:
                continue
            thumb_file = os.path.join(THUMBNAILS_DIR, os.path.basename(thumb_url))
            if not os.path.exists(thumb_file):
                continue
            attempted += 1
            try:
                img = Image.open(thumb_file).convert("RGB")
                inputs = processor(images=img, return_tensors="pt").to(device)
                with torch.no_grad():
                    feats = model.get_image_features(**inputs)
                vec = feats[0].cpu().numpy()
                vec = (vec / (vec ** 2).sum() ** 0.5).tolist()

                qdrant.upsert(
                    collection_name="scenes",
                    points=[PointStruct(
                        id=str(uuid.uuid5(uuid.NAMESPACE_DNS, scene_id)),
                        vector=vec,
                        payload={"scene_id": scene_id, "media_id": media_id},
                    )],
                )
                db.execute(
                    text("UPDATE scenes SET embedding_id = :eid WHERE id = :sid"),
                    {"eid": scene_id, "sid": scene_id},
                )
                embedded += 1
            except Exception as e:
                append_log(db, job_id, f"Scene {scene_id} embed failed: {e}")

        db.commit()
        if attempted > 0 and embedded == 0:
            raise RuntimeError(
                f"All {attempted} scene embeddings failed — check logs above (likely a "
                f"Qdrant dimension mismatch or model load failure)"
            )
        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
        update_asset(db, media_id, processing_stage="visual_embed_complete", processing_progress=90.0)
        append_log(db, job_id, f"Embedded {embedded} scenes ({attempted - embedded} failed)")

    except Exception as e:
        update_job(db, job_id, status="error", error_message=str(e), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()


def _ensure_collection(qdrant, name: str, size: int):
    from qdrant_client.models import Distance, VectorParams
    try:
        info = qdrant.get_collection(name)
        if info.config.params.vectors.size != size:
            qdrant.delete_collection(name)
            qdrant.create_collection(name, vectors_config=VectorParams(size=size, distance=Distance.COSINE))
    except Exception:
        qdrant.create_collection(name, vectors_config=VectorParams(size=size, distance=Distance.COSINE))
