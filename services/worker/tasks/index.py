"""Generate text embeddings for transcript segments and store in Qdrant."""
import uuid
from datetime import datetime
from ..app import celery_app
from ..db import get_session
from .base import update_job, append_log, update_asset
from ..config import QDRANT_URL, EMBEDDINGS_MODEL


@celery_app.task(bind=True, name="tasks.index.build_index", queue="cpu")
def build_index(self, media_id: str, job_id: str):
    db = get_session()
    try:
        update_job(db, job_id, status="running", started_at=datetime.utcnow(), celery_task_id=self.request.id)
        update_asset(db, media_id, processing_stage="indexing", processing_progress=88.0)

        from sqlalchemy import text
        segs = db.execute(
            text("SELECT id, text FROM transcript_segments WHERE media_id = :mid"),
            {"mid": media_id},
        ).fetchall()

        if not segs:
            update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
            update_asset(db, media_id, status="ready", processing_stage="complete", processing_progress=100.0)
            append_log(db, job_id, "No transcript segments to index")
            return

        from sentence_transformers import SentenceTransformer
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams, PointStruct

        append_log(db, job_id, f"Loading embedding model: {EMBEDDINGS_MODEL}")
        model = SentenceTransformer(EMBEDDINGS_MODEL)

        qdrant = QdrantClient(url=QDRANT_URL)
        _ensure_collection(qdrant, "transcripts", model.get_sentence_embedding_dimension())

        texts = [seg[1] for seg in segs]
        append_log(db, job_id, f"Embedding {len(texts)} segments...")
        embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)

        points = []
        for (seg_id, seg_text), emb in zip(segs, embeddings):
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, seg_id))
            points.append(PointStruct(
                id=point_id,
                vector=emb.tolist(),
                payload={"segment_id": seg_id, "media_id": media_id, "text": seg_text[:500]},
            ))

        batch_size = 100
        for i in range(0, len(points), batch_size):
            qdrant.upsert(collection_name="transcripts", points=points[i:i + batch_size])

        db.execute(
            text("UPDATE transcript_segments SET embedding_id = id WHERE media_id = :mid"),
            {"mid": media_id},
        )
        db.commit()

        update_asset(db, media_id, status="ready", processing_stage="complete", processing_progress=100.0)
        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
        append_log(db, job_id, f"Indexed {len(points)} transcript segments")

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
