"""Graphics generation: submit a ComfyUI workflow over HTTP, poll until done,
collect the outputs (single image, image sequence -> mp4, or native video file),
and write results to /artifacts/graphics/<generation_id>/.

Runs on the dedicated "graphics" queue — no GPU reservation in this container;
ComfyUI on the host does the actual GPU work.
"""
import json
import math
import os
import random
import shutil
import subprocess
import tempfile
import time
from datetime import datetime

import requests

from app import celery_app
from db import get_session
from config import COMFYUI_URL, GRAPHICS_DIR, COMFY_WORKFLOWS_DIR
from comfy_graphics import (
    CUSTOM_PRESET_PREFIX,
    builtin_preset,
    detect_capabilities,
    inject_params,
)

POLL_INTERVAL = 1.5
GENERATION_TIMEOUT = int(os.getenv("GRAPHICS_TIMEOUT_SECONDS", "3600"))
# Time-based progress creep while ComfyUI runs (no per-node progress over REST).
RUNNING_ESTIMATE = {"image": 60.0, "video": 600.0}
DEFAULT_FPS = 16

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXTS = {".mp4", ".webm", ".mov", ".mkv", ".avi"}


def _update(db, gen_id: str, **kwargs):
    # "AND status != 'cancelled'": a cancel from the API must never be
    # overwritten by a concurrent worker status write (queued/running/success/
    # error). The poll loop notices the cancelled row on its next iteration
    # and aborts the ComfyUI job.
    from sqlalchemy import text
    set_parts = []
    params = {"gid": gen_id}
    for k, v in kwargs.items():
        if k == "params":
            set_parts.append("params = CAST(:params AS jsonb)")
            params["params"] = json.dumps(v)
        else:
            set_parts.append(f"{k} = :{k}")
            params[k] = v
    db.execute(
        text(
            f"UPDATE graphics_generations SET {', '.join(set_parts)} "
            "WHERE id = :gid AND status != 'cancelled'"
        ),
        params,
    )
    db.commit()


def _fetch_status(db, gen_id: str) -> str | None:
    from sqlalchemy import text
    row = db.execute(
        text("SELECT status FROM graphics_generations WHERE id = :gid"), {"gid": gen_id}
    ).fetchone()
    return row[0] if row else None


def _resolve_graph(preset_id: str) -> tuple[dict, dict]:
    """Return (graph, meta) — meta has kind/fps/steps_hook."""
    b = builtin_preset(preset_id)
    if b is not None:
        return b["graph"], {"kind": b["kind"], "fps": b.get("fps"), "steps_hook": b.get("steps_hook")}
    if preset_id.startswith(CUSTOM_PRESET_PREFIX):
        fname = preset_id[len(CUSTOM_PRESET_PREFIX):]
        path = os.path.join(COMFY_WORKFLOWS_DIR, fname)
        with open(path) as f:
            graph = json.load(f)
        caps = detect_capabilities(graph)
        return graph, {"kind": caps["kind"], "fps": None, "steps_hook": None}
    raise RuntimeError(f"unknown preset '{preset_id}'")


def _comfy_error_detail(payload: dict) -> str:
    parts = []
    err = payload.get("error")
    if isinstance(err, dict) and err.get("message"):
        parts.append(str(err["message"]))
    for node_id, ne in (payload.get("node_errors") or {}).items():
        for e in ne.get("errors", []):
            msg = e.get("message") or e.get("type") or "error"
            detail = e.get("details") or ""
            parts.append(f"node {node_id} ({ne.get('class_type', '?')}): {msg} {detail}".strip())
    return "; ".join(parts) or "ComfyUI rejected the workflow"


def _history_error_detail(entry: dict) -> str:
    status = entry.get("status") or {}
    parts = []
    for msg in status.get("messages", []):
        if isinstance(msg, list) and len(msg) > 1 and msg[0] == "execution_error":
            data = msg[1] or {}
            parts.append(
                f"{data.get('node_type', '?')}: {data.get('exception_message', 'execution error')}"
            )
    return "; ".join(parts) or status.get("status_str") or "ComfyUI execution failed"


def _cancel_in_comfy(prompt_id: str):
    try:
        requests.post(f"{COMFYUI_URL}/queue", json={"delete": [prompt_id]}, timeout=5)
        queue = requests.get(f"{COMFYUI_URL}/queue", timeout=5).json()
        running = {item[1] for item in queue.get("queue_running", []) if len(item) > 1}
        if prompt_id in running:
            requests.post(f"{COMFYUI_URL}/interrupt", timeout=5)
    except Exception:
        pass


def _queue_position(prompt_id: str) -> int | None:
    """None if not queued (running or finished); else 0-based position."""
    queue = requests.get(f"{COMFYUI_URL}/queue", timeout=10).json()
    for idx, item in enumerate(queue.get("queue_pending", [])):
        if len(item) > 1 and item[1] == prompt_id:
            return idx
    return None


def _download_outputs(entry: dict, dest_dir: str) -> list[str]:
    """Download every file output from a history entry, preserving order."""
    files: list[str] = []
    for node_output in (entry.get("outputs") or {}).values():
        for key in ("images", "gifs", "videos", "video", "files"):
            for item in node_output.get(key, []) if isinstance(node_output.get(key), list) else []:
                fname = item.get("filename")
                if not fname:
                    continue
                if item.get("type") not in (None, "output"):
                    continue  # skip temp/preview outputs
                resp = requests.get(
                    f"{COMFYUI_URL}/view",
                    params={
                        "filename": fname,
                        "subfolder": item.get("subfolder", ""),
                        "type": item.get("type", "output"),
                    },
                    timeout=300,
                )
                resp.raise_for_status()
                local = os.path.join(dest_dir, os.path.basename(fname))
                with open(local, "wb") as f:
                    f.write(resp.content)
                files.append(local)
    return files


def _run(cmd: list[str], timeout: int = 600):
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {result.stderr[-400:]}")


def _probe_duration(path: str) -> float | None:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=60,
        )
        return float(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else None
    except Exception:
        return None


def _assemble_output(downloaded: list[str], out_dir: str, kind: str, fps: int | None) -> tuple[str, str, float | None]:
    """Return (output_path, thumbnail_path, duration_seconds)."""
    videos = [f for f in downloaded if os.path.splitext(f)[1].lower() in VIDEO_EXTS]
    images = [f for f in downloaded if os.path.splitext(f)[1].lower() in IMAGE_EXTS]
    thumb = os.path.join(out_dir, "thumb.jpg")

    if videos:
        src = max(videos, key=os.path.getsize)
        output = os.path.join(out_dir, f"output{os.path.splitext(src)[1].lower()}")
        shutil.move(src, output)
        _run(["ffmpeg", "-y", "-i", output, "-vframes", "1", "-vf", "scale=480:-2", thumb])
        return output, thumb, _probe_duration(output)

    if not images:
        raise RuntimeError("ComfyUI reported success but produced no image or video outputs")

    if len(images) == 1 or kind == "image":
        src = sorted(images)[0]
        output = os.path.join(out_dir, f"output{os.path.splitext(src)[1].lower()}")
        shutil.move(src, output)
        _run(["ffmpeg", "-y", "-i", output, "-vf", "scale=480:-2", thumb])
        return output, thumb, None

    # Image sequence -> mp4. SaveImage names frames with an incrementing
    # suffix, so lexicographic order is frame order.
    rate = fps or DEFAULT_FPS
    seq_dir = tempfile.mkdtemp(dir=out_dir)
    for i, src in enumerate(sorted(images)):
        ext = os.path.splitext(src)[1].lower()
        shutil.move(src, os.path.join(seq_dir, f"frame_{i:06d}{ext}"))
    ext = os.path.splitext(sorted(os.listdir(seq_dir))[0])[1]
    output = os.path.join(out_dir, "output.mp4")
    _run([
        "ffmpeg", "-y", "-framerate", str(rate),
        "-i", os.path.join(seq_dir, f"frame_%06d{ext}"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "17", output,
    ], timeout=1800)
    shutil.rmtree(seq_dir, ignore_errors=True)
    _run(["ffmpeg", "-y", "-i", output, "-vframes", "1", "-vf", "scale=480:-2", thumb])
    return output, thumb, _probe_duration(output)


@celery_app.task(bind=True, name="tasks.graphics.generate", queue="graphics")
def generate(self, generation_id: str):
    db = get_session()
    try:
        from sqlalchemy import text
        row = db.execute(
            text("""
                SELECT preset_id, kind, prompt, negative_prompt, width, height,
                       steps, frames, seed, status, params
                FROM graphics_generations WHERE id = :gid
            """),
            {"gid": generation_id},
        ).fetchone()
        if not row:
            return
        (preset_id, kind, prompt, negative, width, height,
         steps, frames, seed, status, params) = row
        if status == "cancelled":
            return

        graph_template, meta = _resolve_graph(preset_id)
        if seed is None:
            seed = random.randint(0, 2**48)

        graph = inject_params(
            graph_template,
            prompt=prompt,
            negative=negative,
            width=width,
            height=height,
            steps=steps,
            frames=frames,
            seed=seed,
            steps_hook=meta.get("steps_hook"),
        )

        out_dir = os.path.join(GRAPHICS_DIR, generation_id)
        os.makedirs(out_dir, exist_ok=True)

        # Retries must be idempotent: clear any partial output from a prior run.
        for stale in os.listdir(out_dir):
            p = os.path.join(out_dir, stale)
            shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.remove(p)

        resp = requests.post(
            f"{COMFYUI_URL}/prompt",
            json={"prompt": graph, "client_id": f"obtv-{generation_id}"},
            timeout=30,
        )
        if resp.status_code != 200:
            try:
                detail = _comfy_error_detail(resp.json())
            except Exception:
                detail = f"ComfyUI returned HTTP {resp.status_code}"
            raise RuntimeError(detail)
        prompt_id = resp.json().get("prompt_id")
        if not prompt_id:
            raise RuntimeError("ComfyUI did not return a prompt_id")

        base_params = params or {}
        _update(db, generation_id,
                status="queued", progress=1.0, seed=seed, comfy_prompt_id=prompt_id,
                params={**base_params, "workflow": graph})

        started = time.time()
        running_since = None
        estimate = RUNNING_ESTIMATE.get(kind, 300.0)
        poll_errors = 0
        while True:
            if time.time() - started > GENERATION_TIMEOUT:
                _cancel_in_comfy(prompt_id)
                raise RuntimeError(f"Timed out after {GENERATION_TIMEOUT}s")

            if _fetch_status(db, generation_id) == "cancelled":
                _cancel_in_comfy(prompt_id)
                return

            # A single blip mustn't kill a long render — only give up after
            # ComfyUI has been unreachable for several consecutive polls.
            try:
                history = requests.get(f"{COMFYUI_URL}/history/{prompt_id}", timeout=10).json()
                poll_errors = 0
            except Exception:
                poll_errors += 1
                if poll_errors >= 8:
                    raise RuntimeError(
                        f"Lost contact with ComfyUI at {COMFYUI_URL} while waiting for the job"
                    )
                time.sleep(POLL_INTERVAL * 2)
                continue
            entry = history.get(prompt_id)
            if entry:
                entry_status = (entry.get("status") or {})
                if entry_status.get("status_str") == "error":
                    raise RuntimeError(_history_error_detail(entry))
                if not entry_status.get("completed", True):
                    raise RuntimeError("ComfyUI execution was interrupted before completion")
                downloaded = _download_outputs(entry, out_dir)
                output, thumb, duration = _assemble_output(downloaded, out_dir, kind, meta.get("fps"))
                _update(db, generation_id,
                        status="success", progress=100.0, queue_position=None,
                        output_path=output, thumbnail_path=thumb,
                        duration_seconds=duration, completed_at=datetime.utcnow())
                return

            try:
                pos = _queue_position(prompt_id)
            except Exception:
                poll_errors += 1
                if poll_errors >= 8:
                    raise RuntimeError(
                        f"Lost contact with ComfyUI at {COMFYUI_URL} while waiting for the job"
                    )
                time.sleep(POLL_INTERVAL * 2)
                continue
            if pos is not None:
                _update(db, generation_id, status="queued",
                        progress=1.0, queue_position=pos)
            else:
                if running_since is None:
                    running_since = time.time()
                creep = min(90.0, 5.0 + (time.time() - running_since) / estimate * 85.0)
                _update(db, generation_id, status="running",
                        progress=math.floor(creep * 10) / 10, queue_position=None)
            time.sleep(POLL_INTERVAL)

    except Exception as exc:
        db.rollback()
        try:
            if _fetch_status(db, generation_id) != "cancelled":
                _update(db, generation_id,
                        status="error", error_message=str(exc)[:2000],
                        completed_at=datetime.utcnow())
        except Exception:
            pass
        raise
    finally:
        db.close()
