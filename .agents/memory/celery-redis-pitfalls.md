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

# Model downloads must be persisted in a volume
Docker worker containers must mount a named volume at `/root/.cache` (HF hub, torch hub, whisper all cache there), or every `docker compose up --build` wipes the models and re-downloads tens of GB on first task.
**Why:** container filesystems are recreated on rebuild; only named volumes survive. Bit us when Qwen 7B (~15 GB) re-downloaded after every worker rebuild.
**How to apply:** declare `models_cache:` in top-level volumes and mount `models_cache:/root/.cache` in EVERY service that loads models — workers AND the api container (the api lazy-loads the Q&A LLM + embedding model; without the mount, the first /ai/ask after a rebuild hangs for minutes re-downloading shards).

# HF from_pretrained spawns subprocesses — forbidden in prefork workers
Loading a hub repo id directly via `from_pretrained` can crash Celery prefork tasks with "daemonic processes are not allowed to have children" (surfaces as a misleading OSError "Can't load the model").
**Why:** transformers spawns a background process to auto-convert legacy `pytorch_model.bin`-only repos (e.g. NLLB) to safetensors; Celery prefork children are daemonic and cannot spawn.
**How to apply:** `snapshot_download(repo_id)` first (thread-based, daemon-safe), then `from_pretrained(local_dir)` — a local path skips hub-side conversion logic. Do NOT switch the worker to `--pool=solo` as a fix: job cancel uses `revoke(terminate=True)`, which requires prefork.

# Lazy model loaders need warm-up + locking in the API
The api warms models in a background daemon thread at startup (non-blocking, healthchecks pass), and the lazy loaders use double-checked locking (`threading.Lock`) so a request racing the warm-up can't load the model twice (double VRAM).
**Why:** first /ai/ask otherwise blocks minutes on model load; an unlocked `if _model is None` check loaded twice under the warm-up race.
**How to apply:** spawn `threading.Thread(target=_warm, daemon=True)` in the FastAPI lifespan after migrations; keep `_load()` guards as `if None: with lock: if None:`.

## Backfill endpoints must check upstream-stage outputs
Re-analyze/backfill endpoints that re-queue mid-pipeline tasks (e.g. face_detect) silently no-op for assets whose upstream outputs (scenes) are missing — a fix to an upstream task only takes effect if the backfill re-runs that stage when its output table is empty.
**Why:** scene_detect start_in_scene fix was deployed but reanalyze only queued diarize+face_detect; zero-scene assets kept logging "No faces" and two threshold changes were blind guesses.
**How to apply:** when adding a backfill route, for each queued stage verify its input rows exist; if not, queue the producing stage instead (it chains downstream).
