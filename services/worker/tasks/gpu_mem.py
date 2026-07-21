"""GPU VRAM hygiene for Celery workers.

The GPU workers share their card with ComfyUI (which the user runs on the
host), so idle VRAM held by cached models is the difference between ComfyUI
working and everything OOMing. Three mechanisms:

1. After every task: gc + torch.cuda.empty_cache() so per-task locals
   (Whisper, SigLIP, pyannote) actually return their VRAM to the driver.
2. Idle release: a watchdog thread in each pool child drops the long-lived
   model caches (Qwen LLM, MADLAD translator, XTTS/Chatterbox TTS, faces)
   after GPU_IDLE_RELEASE_SECONDS with no running task (default 300, 0
   disables).
3. load_with_oom_retry(): model loaders evict all cached models and retry
   once when the first load hits CUDA OOM.
"""
import gc
import logging
import os
import sys
import threading
import time

from celery.signals import task_prerun, task_postrun, worker_process_init

logger = logging.getLogger(__name__)

_IDLE_SECONDS = int(os.getenv("GPU_IDLE_RELEASE_SECONDS", "300") or "0")
_POLL_SECONDS = 30

_lock = threading.Lock()
_active_tasks = 0
_last_activity = time.monotonic()

# (module name, attribute, "none" -> set to None / "clear" -> dict.clear()).
# Only touched if the module is already imported in this process.
_CACHES = [
    ("tasks.analyze", "_llm", "none"),
    ("tasks.translate", "_translator", "none"),
    ("tasks.face_detect", "_face_app", "none"),
    ("tasks.voice", "_xtts_cache", "clear"),
    ("tasks.dub", "_tts_cache", "clear"),
    ("tasks.dub", "_chatterbox_cache", "clear"),
    ("tasks.dub", "_demucs_cache", "clear"),
]


def free_cuda_cache() -> None:
    """gc + release unused cached CUDA blocks back to the driver.

    Only acts if torch was already imported — if it wasn't, this process
    never allocated CUDA memory and importing torch here would be waste.
    """
    gc.collect()
    torch = sys.modules.get("torch")
    if torch is None:
        return
    try:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def release_gpu_models() -> list[str]:
    """Drop every long-lived model cache and empty the CUDA cache."""
    released = []
    for mod_name, attr, mode in _CACHES:
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        cur = getattr(mod, attr, None)
        if not cur:
            continue
        if mode == "clear":
            cur.clear()
        else:
            setattr(mod, attr, None)
        released.append(f"{mod_name}.{attr}")
    free_cuda_cache()
    return released


def is_cuda_oom(exc: BaseException | None) -> bool:
    if exc is None:
        return False
    if type(exc).__name__ == "OutOfMemoryError":
        return True
    msg = str(exc).lower()
    # torch: "CUDA out of memory. Tried to allocate ..."
    # ctranslate2 (faster-whisper): "CUDA failed with error out of memory"
    return "out of memory" in msg and "cuda" in msg


def load_with_oom_retry(name: str, loader):
    """Run a model loader; on CUDA OOM evict all cached models and retry once.

    The retry happens OUTSIDE the except block: retrying inside it keeps the
    failed frame (and its partially-materialized GPU tensors) alive via
    e.__traceback__, which would defeat the release.
    """
    retry = False
    try:
        return loader()
    except Exception as e:
        if not is_cuda_oom(e):
            raise
        retry = True
    if retry:
        released = release_gpu_models()
        logger.warning(
            "CUDA OOM while loading %s — released %s, retrying once",
            name, ", ".join(released) or "nothing",
        )
    return loader()


@task_prerun.connect
def _on_task_prerun(**kwargs):
    global _active_tasks, _last_activity
    with _lock:
        _active_tasks += 1
        _last_activity = time.monotonic()


@task_postrun.connect
def _on_task_postrun(**kwargs):
    global _active_tasks, _last_activity
    with _lock:
        _active_tasks = max(0, _active_tasks - 1)
        _last_activity = time.monotonic()
    free_cuda_cache()


def _watchdog():
    while True:
        time.sleep(_POLL_SECONDS)
        with _lock:
            idle = (
                _active_tasks == 0
                and (time.monotonic() - _last_activity) >= _IDLE_SECONDS
            )
        if not idle:
            continue
        released = release_gpu_models()
        if released:
            logger.info(
                "GPU idle for %ss — released cached models: %s",
                _IDLE_SECONDS, ", ".join(released),
            )
        with _lock:
            _last_activity = time.monotonic()


@worker_process_init.connect
def _start_idle_watchdog(**kwargs):
    if _IDLE_SECONDS <= 0:
        return
    threading.Thread(target=_watchdog, daemon=True, name="gpu-idle-release").start()
