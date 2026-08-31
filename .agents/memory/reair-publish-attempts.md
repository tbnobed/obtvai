---
name: Re-Air publish attempts
description: Why automatic Re-Air Report publication must use one durable attempt.
---

Treat automatic Re-Air Report ingestion as a single durable attempt per report. If a worker interruption leaves the remote outcome unknown, keep the local CSV and surface the ambiguity; do not post that report again.

**Why:** The ingest API does not document an idempotency key or deduplication behavior. Retrying after a timeout, malformed success response, or worker loss could create duplicate reports.

**How to apply:** Any future retry, reaper, or recovery change must preserve the completed CSV while preventing another external POST for a report whose attempt already started. A deliberate new attempt requires creating a new report.