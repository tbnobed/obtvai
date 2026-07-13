import asyncio
import threading
from ..config import settings

_model = None
_model_lock = threading.Lock()
_clip_model = None
_clip_processor = None
_clip_tokenizer = None


def _load_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer
                _model = SentenceTransformer(settings.embeddings_model)
    return _model


def _load_clip():
    global _clip_model, _clip_processor, _clip_tokenizer
    if _clip_model is None:
        import torch
        from transformers import CLIPModel, CLIPProcessor, CLIPTokenizer
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _clip_model = CLIPModel.from_pretrained(settings.vision_model).to(device)
        _clip_processor = CLIPProcessor.from_pretrained(settings.vision_model)
        _clip_tokenizer = CLIPTokenizer.from_pretrained(settings.vision_model)
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
    """CLIP projection dim from config metadata only (no full model load)."""
    try:
        from transformers import AutoConfig
        return AutoConfig.from_pretrained(settings.vision_model).projection_dim
    except Exception:
        model, _, _ = _load_clip()
        return model.config.projection_dim


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
