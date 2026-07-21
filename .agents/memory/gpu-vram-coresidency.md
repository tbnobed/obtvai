---
name: GPU VRAM co-residency
description: Rules for sharing GPUs between the app's model caches and ComfyUI on the prod box
---

The prod GPUs are shared between api/worker containers and host-run ComfyUI.
Idle model caches (Qwen3-8B ~17 GB alone) starve the other side → CUDA OOM
with "GPU has X GiB but only MiB free" even for tiny allocations.

**Rules:**
- Any long-lived model cache (module-level singleton) must have an idle-release
  path: worker caches via `tasks/gpu_mem.py` registry (`GPU_IDLE_RELEASE_SECONDS`),
  api LLM same env, api embeddings `EMBED_IDLE_RELEASE_SECONDS` (longer —
  search is latency-sensitive). New cached models must be registered there.
- After every Celery task: gc + `torch.cuda.empty_cache()` so per-task locals
  return VRAM to the driver (PyTorch's allocator otherwise keeps it reserved
  process-wide, invisible-but-unusable to other processes).
- OOM-retry a model load only OUTSIDE the except block — retrying inside keeps
  `e.__traceback__` (and its partially-materialized GPU tensors) alive, so the
  release frees nothing.
- Celery prefork children are daemonic processes: daemon *threads* inside them
  are fine (watchdogs OK), spawning child *processes* is not.
- `empty_cache()` only affects the torch allocator; ctranslate2 (faster-whisper)
  and onnxruntime (insightface) free VRAM when their objects are GC'd — gc
  first, then empty_cache.

**Why:** July 2026 prod OOM: worker/api process held 21.78 GiB of idle cached
models while ComfyUI held ~73 GiB of a 95 GiB card; a 20 MiB alloc failed.
