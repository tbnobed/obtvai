import asyncio
import gc
import os
import threading
import time
from ..config import settings

_model = None
_model_lock = threading.Lock()
_clip_model = None
_clip_processor = None
_clip_tokenizer = None

# Drop the embedding models from VRAM after this long without a search, so
# ComfyUI and the GPU workers (which share the card) get the memory back.
# Longer default than the LLM's GPU_IDLE_RELEASE_SECONDS because search is
# latency-sensitive and these reload in ~10-20 s. 0 disables.
_IDLE_SECONDS = int(os.getenv("EMBED_IDLE_RELEASE_SECONDS", "1800") or "0")
_last_used = time.monotonic()
_watchdog_started = False


def _release_models():
    global _model, _clip_model, _clip_processor, _clip_tokenizer
    with _model_lock:
        released = _model is not None or _clip_model is not None
        _model = None
        _clip_model = None
        _clip_processor = None
        _clip_tokenizer = None
    if not released:
        return
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    print(f"Embedding models released from VRAM after {_IDLE_SECONDS}s idle")


def _idle_watchdog():
    while True:
        time.sleep(60)
        if (time.monotonic() - _last_used) >= _IDLE_SECONDS:
            _release_models()


def _touch():
    global _last_used, _watchdog_started
    _last_used = time.monotonic()
    if _IDLE_SECONDS > 0:
        with _model_lock:
            if not _watchdog_started:
                _watchdog_started = True
                threading.Thread(
                    target=_idle_watchdog, daemon=True, name="embed-idle-release"
                ).start()


def _load_model():
    global _model
    _touch()
    if _model is None:
        with _model_lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer
                _model = SentenceTransformer(settings.embeddings_model)
    return _model


def _is_siglip() -> bool:
    return "siglip" in settings.vision_model.lower()


def _load_clip():
    global _clip_model, _clip_processor, _clip_tokenizer
    _touch()
    if _clip_model is None:
        import torch
        from transformers import AutoModel, AutoProcessor, AutoTokenizer
        device = "cuda" if torch.cuda.is_available() else "cpu"
        # AutoModel handles both CLIP and SigLIP/SigLIP-2 checkpoints; both
        # expose get_image_features / get_text_features in a shared space.
        _clip_model = AutoModel.from_pretrained(settings.vision_model).to(device).eval()
        _clip_processor = AutoProcessor.from_pretrained(settings.vision_model)
        _clip_tokenizer = AutoTokenizer.from_pretrained(settings.vision_model)
    return _clip_model, _clip_processor, _clip_tokenizer


def get_text_vector_size() -> int:
    """Embedding dim from config metadata only (no full model load).
    Falls back to loading the model for architectures with a projection head."""
    try:
        from transformers import AutoConfig
        return AutoConfig.from_pretrained(settings.embeddings_model).hidden_size
    except Exception:
        return _load_model().get_sentence_embedding_dimension()


def get_clip_vector_size() -> int:
    """Vision embedding dim from config metadata only (no full model load).
    CLIP has a projection head; SigLIP/SigLIP-2 embed at the tower hidden size."""
    try:
        from transformers import AutoConfig
        cfg = AutoConfig.from_pretrained(settings.vision_model)
        dim = getattr(cfg, "projection_dim", None)
        if dim:
            return int(dim)
        return int(cfg.text_config.hidden_size)
    except Exception:
        model, _, _ = _load_clip()
        cfg = model.config
        return int(getattr(cfg, "projection_dim", None) or cfg.text_config.hidden_size)


async def get_text_embedding(text: str) -> list[float]:
    loop = asyncio.get_event_loop()

    def _run():
        model = _load_model()
        vec = model.encode(text, normalize_embeddings=True)
        return vec.tolist()

    return await loop.run_in_executor(None, _run)


async def get_clip_text_embedding(text: str) -> list[float]:
    """Embed a text query into CLIP space for visual (scene) search."""
    import torch
    loop = asyncio.get_event_loop()

    def _run():
        model, _, tokenizer = _load_clip()
        device = next(model.parameters()).device
        if _is_siglip():
            # SigLIP text towers are trained with fixed-length 64-token padding;
            # matching it at query time is required for sane similarity scores.
            inputs = tokenizer(
                [text], padding="max_length", max_length=64,
                truncation=True, return_tensors="pt",
            ).to(device)
        else:
            inputs = tokenizer([text], padding=True, truncation=True, return_tensors="pt").to(device)
        with torch.no_grad():
            features = model.get_text_features(**inputs)
        vec = features[0].cpu().numpy()
        vec = vec / (vec ** 2).sum() ** 0.5
        return vec.tolist()

    return await loop.run_in_executor(None, _run)


async def get_image_embedding(image_path: str) -> list[float]:
    import torch
    from PIL import Image
    loop = asyncio.get_event_loop()

    def _run():
        model, processor, _ = _load_clip()
        device = next(model.parameters()).device
        image = Image.open(image_path).convert("RGB")
        inputs = processor(images=image, return_tensors="pt").to(device)
        with torch.no_grad():
            features = model.get_image_features(**inputs)
        vec = features[0].cpu().numpy()
        vec = vec / (vec ** 2).sum() ** 0.5
        return vec.tolist()

    return await loop.run_in_executor(None, _run)
