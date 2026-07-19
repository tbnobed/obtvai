"""Graphics generator: drives the host's existing ComfyUI install over HTTP.

The API validates presets against ComfyUI's /object_info (which node classes
exist and which model files each loader can see) and enqueues generations on
the dedicated "graphics" Celery queue; the worker submits the workflow to
ComfyUI and collects outputs. Custom ComfyUI workflows (API-format JSON
exports) dropped into the mounted workflows folder appear as extra presets.
"""
import json
import os
import shutil
import time
import uuid
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from ..database import get_db
from ..models import GraphicsGeneration, MediaAsset
from ..schemas import (
    GraphicsPresetOut,
    GraphicsGenerateIn,
    GraphicsGenerationOut,
    GraphicsGenerationListOut,
)
from ..config import settings
from .. import worker_client
from ..comfy_graphics import (
    BUILTIN_PRESETS,
    CUSTOM_PRESET_PREFIX,
    builtin_preset,
    detect_capabilities,
    check_graph,
)

router = APIRouter(tags=["graphics"])

ACTIVE_STATUSES = {"pending", "queued", "running"}
MAX_DIM = 4096
MAX_FRAMES = 481
MAX_STEPS = 100

# /object_info is a big payload; cache it briefly so the presets endpoint can
# be polled without hammering ComfyUI.
_object_info_cache: dict = {"data": None, "error": None, "ts": 0.0}
OBJECT_INFO_TTL = 30.0


async def _get_object_info() -> tuple[dict | None, str | None]:
    now = time.monotonic()
    if now - _object_info_cache["ts"] < OBJECT_INFO_TTL:
        return _object_info_cache["data"], _object_info_cache["error"]
    data, error = None, None
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(f"{settings.comfyui_url}/object_info")
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # unreachable, timeout, bad JSON — all mean "not available"
        error = f"ComfyUI unreachable at {settings.comfyui_url} ({type(exc).__name__})"
    _object_info_cache.update({"data": data, "error": error, "ts": now})
    return data, error


def _load_custom_workflows() -> list[tuple[str, str, dict | None, str | None]]:
    """[(preset_id, filename, graph|None, parse_error|None)] from the workflows dir."""
    out = []
    wf_dir = settings.comfy_workflows_dir
    if not os.path.isdir(wf_dir):
        return out
    for fname in sorted(os.listdir(wf_dir)):
        if not fname.lower().endswith(".json") or fname.startswith("."):
            continue
        preset_id = f"{CUSTOM_PRESET_PREFIX}{fname}"
        path = os.path.join(wf_dir, fname)
        try:
            with open(path) as f:
                graph = json.load(f)
            if not isinstance(graph, dict) or not graph:
                raise ValueError("not a JSON object")
            first = next(iter(graph.values()))
            if not isinstance(first, dict) or "class_type" not in first:
                raise ValueError('no class_type — export with "Export (API format)" in ComfyUI')
            out.append((preset_id, fname, graph, None))
        except Exception as exc:
            out.append((preset_id, fname, None, str(exc)))
    return out


def _resolve_preset(preset_id: str) -> tuple[dict | None, dict | None, str | None]:
    """Return (meta, graph, error) for a builtin or custom preset id."""
    b = builtin_preset(preset_id)
    if b is not None:
        return b, b["graph"], None
    if preset_id.startswith(CUSTOM_PRESET_PREFIX):
        fname = preset_id[len(CUSTOM_PRESET_PREFIX):]
        if os.path.basename(fname) != fname:
            return None, None, "invalid preset id"
        path = os.path.join(settings.comfy_workflows_dir, fname)
        if not os.path.isfile(path):
            return None, None, f"workflow file '{fname}' not found"
        try:
            with open(path) as f:
                graph = json.load(f)
        except Exception as exc:
            return None, None, f"workflow file '{fname}' is not valid JSON: {exc}"
        caps = detect_capabilities(graph)
        meta = {
            "id": preset_id,
            "name": os.path.splitext(fname)[0],
            "kind": caps["kind"],
            "fps": None,
            **{k: caps[k] for k in (
                "supports_negative", "supports_size", "supports_steps",
                "supports_frames", "supports_seed",
                "default_width", "default_height", "default_steps", "default_frames",
            )},
        }
        return meta, graph, None
    return None, None, f"unknown preset '{preset_id}'"


def _gen_out(g: GraphicsGeneration) -> GraphicsGenerationOut:
    done = g.status == "success"
    return GraphicsGenerationOut(
        id=g.id,
        kind=g.kind,
        preset_id=g.preset_id,
        preset_name=g.preset_name,
        prompt=g.prompt,
        negative=g.negative_prompt,
        status=g.status,
        progress=g.progress or 0.0,
        queue_position=g.queue_position,
        error_message=g.error_message,
        width=g.width,
        height=g.height,
        frames=g.frames,
        seed=g.seed,
        duration_seconds=g.duration_seconds,
        output_url=f"/api/graphics/generations/{g.id}/output" if done and g.output_path else None,
        thumbnail_url=f"/api/graphics/generations/{g.id}/thumbnail" if done and g.thumbnail_path else None,
        media_id=g.media_id,
        created_at=g.created_at,
        completed_at=g.completed_at,
    )


@router.get("/graphics/presets", response_model=list[GraphicsPresetOut])
async def list_graphics_presets():
    object_info, comfy_error = await _get_object_info()
    presets: list[GraphicsPresetOut] = []

    def availability(graph: dict | None, parse_error: str | None) -> tuple[bool, str | None]:
        if parse_error:
            return False, parse_error
        if comfy_error:
            return False, comfy_error
        reason = check_graph(graph, object_info or {})
        return (reason is None), reason

    for b in BUILTIN_PRESETS:
        ok, reason = availability(b["graph"], None)
        presets.append(GraphicsPresetOut(
            id=b["id"], name=b["name"], description=b["description"],
            kind=b["kind"], source="builtin", available=ok, unavailable_reason=reason,
            supports_negative=b["supports_negative"], supports_size=b["supports_size"],
            supports_steps=b["supports_steps"], supports_frames=b["supports_frames"],
            supports_seed=b["supports_seed"],
            default_width=b["default_width"], default_height=b["default_height"],
            default_steps=b["default_steps"], default_frames=b["default_frames"],
        ))

    for preset_id, fname, graph, parse_error in _load_custom_workflows():
        ok, reason = availability(graph, parse_error)
        caps = detect_capabilities(graph) if graph else {
            "kind": "image", "supports_negative": False, "supports_size": False,
            "supports_steps": False, "supports_frames": False, "supports_seed": False,
            "default_width": None, "default_height": None,
            "default_steps": None, "default_frames": None,
        }
        presets.append(GraphicsPresetOut(
            id=preset_id, name=os.path.splitext(fname)[0],
            description=f"Custom ComfyUI workflow ({fname})",
            kind=caps["kind"], source="custom", available=ok, unavailable_reason=reason,
            supports_negative=caps["supports_negative"], supports_size=caps["supports_size"],
            supports_steps=caps["supports_steps"], supports_frames=caps["supports_frames"],
            supports_seed=caps["supports_seed"],
            default_width=caps["default_width"], default_height=caps["default_height"],
            default_steps=caps["default_steps"], default_frames=caps["default_frames"],
        ))
    return presets


@router.post("/graphics/generations", response_model=GraphicsGenerationOut, status_code=202)
async def create_graphics_generation(body: GraphicsGenerateIn, db: AsyncSession = Depends(get_db)):
    if not body.prompt or not body.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is required")
    meta, graph, err = _resolve_preset(body.preset_id)
    if err:
        raise HTTPException(status_code=404, detail=err)

    object_info, comfy_error = await _get_object_info()
    if comfy_error:
        raise HTTPException(status_code=503, detail=comfy_error)
    reason = check_graph(graph, object_info or {})
    if reason:
        raise HTTPException(status_code=409, detail=f"Preset unavailable: {reason}")

    if body.width is not None and not (16 <= body.width <= MAX_DIM):
        raise HTTPException(status_code=400, detail=f"width must be 16-{MAX_DIM}")
    if body.height is not None and not (16 <= body.height <= MAX_DIM):
        raise HTTPException(status_code=400, detail=f"height must be 16-{MAX_DIM}")
    if body.steps is not None and not (1 <= body.steps <= MAX_STEPS):
        raise HTTPException(status_code=400, detail=f"steps must be 1-{MAX_STEPS}")
    if body.frames is not None and not (1 <= body.frames <= MAX_FRAMES):
        raise HTTPException(status_code=400, detail=f"frames must be 1-{MAX_FRAMES}")
    if body.seed is not None and not (0 <= body.seed < 2**63):
        raise HTTPException(status_code=400, detail="seed out of range")

    gen = GraphicsGeneration(
        preset_id=body.preset_id,
        preset_name=meta["name"],
        kind=meta["kind"],
        prompt=body.prompt.strip(),
        negative_prompt=(body.negative or None),
        width=body.width or meta.get("default_width"),
        height=body.height or meta.get("default_height"),
        steps=body.steps or meta.get("default_steps"),
        frames=(body.frames or meta.get("default_frames")) if meta["kind"] == "video" else None,
        seed=body.seed,
        status="pending",
        progress=0.0,
        params={"request": body.model_dump()},
    )
    db.add(gen)
    await db.commit()
    await db.refresh(gen)
    await worker_client.enqueue_graphics(gen.id)
    return _gen_out(gen)


@router.get("/graphics/generations", response_model=GraphicsGenerationListOut)
async def list_graphics_generations(limit: int = 50, offset: int = 0, db: AsyncSession = Depends(get_db)):
    limit = max(1, min(limit, 200))
    total = (await db.execute(select(func.count(GraphicsGeneration.id)))).scalar() or 0
    rows = (await db.execute(
        select(GraphicsGeneration)
        .order_by(GraphicsGeneration.created_at.desc())
        .limit(limit).offset(max(0, offset))
    )).scalars().all()
    return GraphicsGenerationListOut(items=[_gen_out(g) for g in rows], total=total)


async def _get_gen(gen_id: str, db: AsyncSession) -> GraphicsGeneration:
    gen = (await db.execute(
        select(GraphicsGeneration).where(GraphicsGeneration.id == gen_id)
    )).scalar_one_or_none()
    if gen is None:
        raise HTTPException(status_code=404, detail="Generation not found")
    return gen


@router.get("/graphics/generations/{gen_id}", response_model=GraphicsGenerationOut)
async def get_graphics_generation(gen_id: str, db: AsyncSession = Depends(get_db)):
    return _gen_out(await _get_gen(gen_id, db))


async def _comfy_abort(prompt_id: str | None):
    """Best-effort: drop a queued prompt and interrupt it if it's running."""
    if not prompt_id:
        return
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{settings.comfyui_url}/queue", json={"delete": [prompt_id]})
            queue = (await client.get(f"{settings.comfyui_url}/queue")).json()
            running_ids = {item[1] for item in queue.get("queue_running", []) if len(item) > 1}
            if prompt_id in running_ids:
                await client.post(f"{settings.comfyui_url}/interrupt")
    except Exception:
        pass  # worker also watches for the cancelled status


@router.post("/graphics/generations/{gen_id}/cancel", response_model=GraphicsGenerationOut)
async def cancel_graphics_generation(gen_id: str, db: AsyncSession = Depends(get_db)):
    gen = await _get_gen(gen_id, db)
    if gen.status not in ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail=f"Generation is {gen.status}, nothing to cancel")
    gen.status = "cancelled"
    gen.completed_at = datetime.utcnow()
    await db.commit()
    await db.refresh(gen)
    await _comfy_abort(gen.comfy_prompt_id)
    return _gen_out(gen)


@router.delete("/graphics/generations/{gen_id}", status_code=204)
async def delete_graphics_generation(gen_id: str, db: AsyncSession = Depends(get_db)):
    gen = await _get_gen(gen_id, db)
    if gen.status in ACTIVE_STATUSES:
        gen.status = "cancelled"
        await db.commit()
        await _comfy_abort(gen.comfy_prompt_id)
    out_dir = os.path.join(settings.graphics_dir, gen.id)
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir, ignore_errors=True)
    await db.delete(gen)
    await db.commit()


def _serve_file(path: str | None, download_name: str | None = None) -> FileResponse:
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not available")
    ext = os.path.splitext(path)[1].lower()
    media_type = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".mp4": "video/mp4", ".webm": "video/webm",
    }.get(ext, "application/octet-stream")
    kwargs = {"media_type": media_type}
    if download_name:
        kwargs["filename"] = f"{download_name}{ext}"
    return FileResponse(path, **kwargs)


@router.get("/graphics/generations/{gen_id}/output")
async def get_graphics_output(gen_id: str, db: AsyncSession = Depends(get_db)):
    gen = await _get_gen(gen_id, db)
    return _serve_file(gen.output_path, download_name=f"graphics_{gen.id[:8]}")


@router.get("/graphics/generations/{gen_id}/thumbnail")
async def get_graphics_thumbnail(gen_id: str, db: AsyncSession = Depends(get_db)):
    gen = await _get_gen(gen_id, db)
    return _serve_file(gen.thumbnail_path)


@router.post("/graphics/generations/{gen_id}/add-to-library", response_model=GraphicsGenerationOut, status_code=202)
async def add_graphics_to_library(gen_id: str, db: AsyncSession = Depends(get_db)):
    gen = await _get_gen(gen_id, db)
    if gen.kind != "video":
        raise HTTPException(status_code=400, detail="Only video generations can be added to the library")
    if gen.status != "success" or not gen.output_path or not os.path.isfile(gen.output_path):
        raise HTTPException(status_code=409, detail="Generation has no finished output")
    if gen.media_id:
        raise HTTPException(status_code=409, detail="Already added to the library")

    os.makedirs(settings.upload_dir, exist_ok=True)
    asset_id = str(uuid.uuid4())
    ext = os.path.splitext(gen.output_path)[1] or ".mp4"
    safe_name = f"generated_{(gen.preset_name or gen.preset_id).replace(' ', '_')[:40]}_{gen.id[:8]}{ext}"
    dest_path = os.path.join(settings.upload_dir, f"{asset_id}_{safe_name}")
    from fastapi.concurrency import run_in_threadpool
    await run_in_threadpool(shutil.copyfile, gen.output_path, dest_path)

    asset = MediaAsset(
        id=asset_id,
        filename=safe_name,
        original_path=dest_path,
        status="pending",
        file_size_bytes=os.path.getsize(dest_path),
        created_at=datetime.utcnow(),
    )
    db.add(asset)
    gen.media_id = asset_id
    await db.commit()
    await db.refresh(gen)
    await worker_client.enqueue_ingest(asset_id)
    return _gen_out(gen)
