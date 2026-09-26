---
name: Archive memory safety
description: Why archive caches use database invalidation and must remain optional to answering.
---

Archive cache invalidation must observe committed database mutations, not just API/ORM events.

**Why:** Analysis workers write through raw SQL in separate processes. API-only invalidation would leave plausible but stale archive totals and routing summaries after ordinary ingestion.

**How to apply:** Preserve transactional invalidation when adding write paths; an edit or deletion during embedding must remain pending after the older indexing attempt finishes.

Optional cache failure must not discard an otherwise valid measured answer or abort the enclosing conversation transaction. Failures computing the actual facts must still surface.

**Why:** A cache-row lock timeout can occur after successful measurement. Catching it without rolling back a savepoint leaves PostgreSQL's enclosing transaction unusable.

**How to apply:** Isolate cache operations, test real lock contention with a subsequent conversation write, and never convert failed measurement into a cached zero.