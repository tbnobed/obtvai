from typing import Optional
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
)
from ..config import settings

_client: Optional[AsyncQdrantClient] = None


def get_client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(url=settings.qdrant_url)
    return _client


async def ensure_collections():
    """Create collections sized to their embedding models:
    transcripts -> sentence-transformer dims, scenes -> CLIP projection dims.

    If an existing collection has a different vector size (e.g. after switching
    embedding models), it is dropped and recreated — vectors are derivable data
    and are rebuilt by re-running indexing jobs."""
    import logging
    from .embedding import get_text_vector_size, get_clip_vector_size
    logger = logging.getLogger("obtv.qdrant")
    client = get_client()
    sizes = {
        "transcripts": get_text_vector_size(),
        "scenes": get_clip_vector_size(),
    }
    for collection, size in sizes.items():
        try:
            info = await client.get_collection(collection)
            existing = info.config.params.vectors.size
            if existing != size:
                logger.warning(
                    "Collection '%s' has vector size %d but model produces %d — "
                    "recreating. Re-run indexing jobs to repopulate.",
                    collection, existing, size,
                )
                await client.delete_collection(collection)
                await client.create_collection(
                    collection_name=collection,
                    vectors_config=VectorParams(size=size, distance=Distance.COSINE),
                )
        except Exception:
            await client.create_collection(
                collection_name=collection,
                vectors_config=VectorParams(size=size, distance=Distance.COSINE),
            )


async def upsert_vector(collection: str, id: str, vector: list[float], payload: dict):
    client = get_client()
    await client.upsert(
        collection_name=collection,
        points=[PointStruct(id=id, vector=vector, payload=payload)],
    )


async def search_vectors(
    collection: str,
    vector: list[float],
    limit: int = 20,
    media_id: Optional[str] = None,
):
    client = get_client()
    query_filter = None
    if media_id:
        query_filter = Filter(
            must=[FieldCondition(key="media_id", match=MatchValue(value=media_id))]
        )
    results = await client.search(
        collection_name=collection,
        query_vector=vector,
        limit=limit,
        query_filter=query_filter,
        with_payload=True,
    )
    return results


async def delete_by_media_id(collection: str, media_id: str):
    client = get_client()
    from qdrant_client.models import FilterSelector
    await client.delete(
        collection_name=collection,
        points_selector=FilterSelector(
            filter=Filter(
                must=[FieldCondition(key="media_id", match=MatchValue(value=media_id))]
            )
        ),
    )
