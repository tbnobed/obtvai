"""Shared Qdrant helpers for worker tasks.

The qdrant-client REST default timeout is 5s; under heavy parallel ingest
(multiple workers upserting while the API searches) Qdrant can take longer
than that, surfacing as bare "timed out" job errors. Use a generous timeout
plus bounded retries with backoff for transient failures.
"""
import time

from config import QDRANT_URL

QDRANT_TIMEOUT = 120  # seconds


def get_qdrant():
    from qdrant_client import QdrantClient
    return QdrantClient(url=QDRANT_URL, timeout=QDRANT_TIMEOUT)


def qdrant_retry(fn, *args, attempts: int = 4, base_delay: float = 2.0, **kwargs):
    """Call fn(*args, **kwargs), retrying on transient errors with backoff."""
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if attempt == attempts:
                break
            time.sleep(base_delay * (2 ** (attempt - 1)))
    raise last_exc
