---
name: Person identity concurrency
description: Locking and dedupe rules for the people/identify/insights subsystem
---

**Rule:** Any mutation of Person/PersonAppearance rows (API merge, worker identify) must hold the same Postgres advisory lock — `hashtext('obtv_identify')` — API side uses `pg_advisory_xact_lock` and re-reads rows after acquiring it.
**Why:** The identify worker operates on an in-memory snapshot of all people; an unlocked merge interleaving with it recreates duplicates or writes stale assignments (architect-flagged race).
**How to apply:** New endpoints or tasks touching person identity take the lock first, then re-fetch. Merge must *blend* (average + renormalize) embeddings, not copy-if-missing, or the next identify run re-splits the merged person.

**Rule:** Singleton job types (e.g. library-wide insights) are deduped by a partial unique index on `processing_jobs (job_type) WHERE status IN ('pending','running')`, with the API catching IntegrityError and returning the existing job.
**Why:** Check-then-insert dedupe in the endpoint is racy under concurrent requests.
