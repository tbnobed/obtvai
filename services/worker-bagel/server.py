"""BAGEL inference server — image captioning and text-to-image generation.

Loads the ByteDance-Seed/BAGEL-7B-MoT model once at startup, then serves:
  POST /caption  — image (base64) → natural-language description
  POST /generate — text prompt → image (base64)
  GET  /health   — liveness / readiness probe
"""

import base64
import io
import logging
import os
import threading
import time

import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("bagel-server")

MODEL_PATH = os.environ.get("BAGEL_MODEL_PATH", "/app/model")
PORT = int(os.environ.get("PORT", "8003"))

# ---------------------------------------------------------------------------
# Global model state (populated by the background loader thread)
# ---------------------------------------------------------------------------
_inferencer = None
_ready = False
_load_error: str | None = None
# One forward pass at a time — BAGEL is not thread-safe for concurrent use.
_infer_lock = threading.Lock()


def _load_model():
    global _inferencer, _ready, _load_error
    try:
        logger.info("Loading BAGEL from %s", MODEL_PATH)
        t0 = time.time()

        # Lazy-import BAGEL repo code (lives in /app/bagel via PYTHONPATH).
        from accelerate import (  # type: ignore
            infer_auto_device_map,
            init_empty_weights,
            load_checkpoint_and_dispatch,
        )
        from data.data_utils import add_special_tokens  # type: ignore
        from data.transforms import ImageTransform  # type: ignore
        from inferencer import InterleaveInferencer  # type: ignore
        from modeling.autoencoder import load_ae  # type: ignore
        from modeling.bagel import (  # type: ignore
            Bagel,
            BagelConfig,
            Qwen2Config,
            Qwen2ForCausalLM,
            SiglipVisionConfig,
            SiglipVisionModel,
        )
        from modeling.qwen2 import Qwen2Tokenizer  # type: ignore

        # Download weights from HuggingFace on first run.
        ema_path = os.path.join(MODEL_PATH, "ema.safetensors")
        if not os.path.exists(ema_path):
            logger.info("Weights not found — downloading ByteDance-Seed/BAGEL-7B-MoT …")
            from huggingface_hub import snapshot_download  # type: ignore
            snapshot_download(
                repo_id="ByteDance-Seed/BAGEL-7B-MoT",
                local_dir=MODEL_PATH,
                ignore_patterns=["*.msgpack", "*.h5", "flax_model*"],
            )

        # Build model config exactly as BAGEL's own app.py does.
        llm_config = Qwen2Config.from_json_file(os.path.join(MODEL_PATH, "llm_config.json"))
        llm_config.qk_norm = True
        llm_config.tie_word_embeddings = False
        llm_config.layer_module = "Qwen2MoTDecoderLayer"

        vit_config = SiglipVisionConfig.from_json_file(os.path.join(MODEL_PATH, "vit_config.json"))
        vit_config.rope = False
        vit_config.num_hidden_layers -= 1

        vae_model, vae_config = load_ae(local_path=os.path.join(MODEL_PATH, "ae.safetensors"))

        config = BagelConfig(
            visual_gen=True,
            visual_und=True,
            llm_config=llm_config,
            vit_config=vit_config,
            vae_config=vae_config,
            vit_max_num_patch_per_side=70,
            connector_act="gelu_pytorch_tanh",
            latent_patch_size=2,
            max_latent_size=64,
        )

        with init_empty_weights():
            language_model = Qwen2ForCausalLM(llm_config)
            vit_model = SiglipVisionModel(vit_config)
            model = Bagel(language_model, vit_model, config)
            model.vit_model.vision_model.embeddings.convert_conv2d_to_linear(vit_config, meta=True)

        tokenizer = Qwen2Tokenizer.from_pretrained(MODEL_PATH)
        tokenizer, new_token_ids, _ = add_special_tokens(tokenizer)

        vae_transform = ImageTransform(1024, 512, 16)
        vit_transform = ImageTransform(980, 224, 14)

        # Spread layers across all visible GPUs; keep projection modules
        # co-resident on the first device to avoid cross-device op errors.
        #
        # On unified-memory systems (GB10) other processes (e.g. vLLM) share
        # the same physical pool, so we query *actual* free memory instead of
        # assuming the whole device is available.
        n_gpus = torch.cuda.device_count()
        if n_gpus > 0:
            free_bytes, total_bytes = torch.cuda.mem_get_info(0)
            # Keep 3 GiB headroom; don't request more than 80 GiB per device.
            avail_gib = min(80, max(4, int(free_bytes / (1024 ** 3)) - 3))
            logger.info(
                "GPU 0: %.1f GiB free, allocating %d GiB for BAGEL",
                free_bytes / (1024 ** 3),
                avail_gib,
            )
            max_memory = {i: f"{avail_gib}GiB" for i in range(n_gpus)}
        else:
            logger.warning("No CUDA GPUs visible — loading BAGEL on CPU")
            max_memory = {"cpu": "28GiB"}

        device_map = infer_auto_device_map(
            model,
            max_memory=max_memory,
            no_split_module_classes=["Bagel", "Qwen2MoTDecoderLayer"],
        )
        same_device_modules = [
            "language_model.model.embed_tokens",
            "time_embedder",
            "latent_pos_embed",
            "vae2llm",
            "llm2vae",
            "connector",
            "vit_pos_embed",
        ]
        first_device = device_map.get(same_device_modules[0], "cuda:0")
        for k in same_device_modules:
            device_map[k] = first_device

        model = load_checkpoint_and_dispatch(
            model,
            checkpoint=ema_path,
            device_map=device_map,
            offload_buffers=True,
            offload_folder="/tmp/offload",
            dtype=torch.bfloat16,
            force_hooks=True,
        ).eval()

        _inferencer = InterleaveInferencer(
            model, vae_model, tokenizer, vae_transform, vit_transform, new_token_ids
        )
        _ready = True
        logger.info("BAGEL ready in %.1fs", time.time() - t0)

    except Exception:
        import traceback
        _load_error = traceback.format_exc()
        logger.exception("BAGEL model load failed")


# Start loading in the background so /health is available immediately.
threading.Thread(target=_load_model, daemon=True).start()

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="BAGEL Inference Server", version="1.0")

_DEFAULT_CAPTION_PROMPT = (
    "You are assisting a professional video editor. "
    "Describe this video frame concisely: who is in the frame, "
    "what they are doing, the setting or location, any visible text or "
    "lower-thirds, and the overall mood. Be factual and specific. "
    "Write 2–3 sentences maximum."
)


@app.get("/health")
def health():
    if _load_error:
        return JSONResponse({"status": "error", "detail": _load_error[:500]}, status_code=503)
    if not _ready:
        return JSONResponse({"status": "loading"}, status_code=503)
    return {"status": "ok", "device_count": torch.cuda.device_count()}


# ── Captioning ───────────────────────────────────────────────────────────────

class CaptionRequest(BaseModel):
    image_b64: str
    prompt: str = _DEFAULT_CAPTION_PROMPT
    max_tokens: int = 200


class CaptionResponse(BaseModel):
    caption: str
    elapsed_ms: int


@app.post("/caption", response_model=CaptionResponse)
def caption(req: CaptionRequest):
    if not _ready:
        raise HTTPException(503, "Model not ready")
    try:
        pil_image = Image.open(io.BytesIO(base64.b64decode(req.image_b64))).convert("RGB")
    except Exception as exc:
        raise HTTPException(400, f"Invalid image: {exc}")

    t0 = time.time()
    with _infer_lock:
        result = _inferencer.interleave_inference(
            input_lists=[req.prompt, pil_image],
            understanding_output=True,
            do_sample=False,
            text_temperature=0.3,
            max_think_token_n=req.max_tokens,
        )
    caption_text = (result[0] if result else "").strip()
    return CaptionResponse(caption=caption_text, elapsed_ms=int((time.time() - t0) * 1000))


# ── Image generation ─────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    prompt: str
    width: int = 1024
    height: int = 1024
    cfg_text_scale: float = 4.0
    num_timesteps: int = 50


class GenerateResponse(BaseModel):
    image_b64: str
    elapsed_ms: int


@app.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest):
    if not _ready:
        raise HTTPException(503, "Model not ready")

    t0 = time.time()
    with _infer_lock:
        result = _inferencer.interleave_inference(
            input_lists=[req.prompt],
            understanding_output=False,
            do_sample=True,
            cfg_text_scale=req.cfg_text_scale,
            num_timesteps=req.num_timesteps,
            image_shapes=(req.height, req.width),
        )

    pil_out = result[0] if result else None
    if not isinstance(pil_out, Image.Image):
        raise HTTPException(500, "Generation produced no image")

    buf = io.BytesIO()
    pil_out.save(buf, format="JPEG", quality=92)
    return GenerateResponse(
        image_b64=base64.b64encode(buf.getvalue()).decode(),
        elapsed_ms=int((time.time() - t0) * 1000),
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
