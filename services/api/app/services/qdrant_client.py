from typing import Optional
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
)
from ..config import settings

_client: Optional[AsyncQdrantClient] = None
VECTOR_SIZE = 384


def get_client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(url=settings.qdrant_url)
    return _client


async def ensure_collections():
    client = get_client()
    for collection in ("transcripts", "scenes"):
        try:
            await client.get_collection(collection)
        except Exception:
            await client.create_collection(
                collection_name=collection,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
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
