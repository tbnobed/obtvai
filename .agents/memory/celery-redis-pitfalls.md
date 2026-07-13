---
name: Celery/SQLAlchemy worker pitfalls
description: Wire-format and SQL binding rules for the API→Redis→Celery worker pipeline
---

# Celery message format
Never push hand-rolled JSON to a Redis list that Celery workers consume — workers crash with `KeyError('properties')` in kombu (missing message envelope).
**Why:** Celery expects the full kombu wire format (properties/headers/base64 body), not `{"task": ..., "kwargs": ...}`.
**How to apply:** Publish from any producer (including FastAPI) via a Celery client's `send_task(name, kwargs=..., queue=..., task_id=...)`; in async code wrap it in `run_in_threadpool`.

# SQLAlchemy text() + Postgres casts
`text("... :param::jsonb ...")` does NOT bind the parameter — the literal `:param` reaches Postgres ("syntax error at or near :").
**Why:** SQLAlchemy's bind-param lexer refuses names immediately followed by `::`.
**How to apply:** Use `CAST(:param AS jsonb)` instead of `::` casts adjacent to bind params. Build JSON values with `json.dumps`, never f-strings.

# Aborted-transaction error handlers
Worker task `except` blocks must call `db.rollback()` before writing error status, or the write fails with `InFailedSqlTransaction` and masks the real error.

# Heavy model loading in worker tasks
Cache large models (LLMs, whisper, CLIP) in a module-level global inside the task module, loaded lazily on first use — never load inside the task function body per invocation.
**Why:** A 7B LLM load takes minutes and fragments GPU memory when repeated; worker processes are long-lived so a module cache persists across jobs.
**How to apply:** `_model = None` + `_load()` guard at module scope (same pattern as the API's llm service). Concurrency=1 on the gpu queue keeps this safe.
