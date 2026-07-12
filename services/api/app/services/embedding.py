from functools import lru_cache
from typing import Optional
import asyncio
from ..config import settings

_model = None


def _load_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(settings.embeddings_model)
    return _model


async def get_text_embedding(text: str) -> list[float]:
    loop = asyncio.get_event_loop()
    def _run():
        model = _load_model()
        vec = model.encode(text, normalize_embeddings=True)
        return vec.tolist()
    return await loop.run_in_executor(None, _run)


async def get_image_embedding(image_path: str) -> list[float]:
    import torch
    from PIL import Image
    from transformers import CLIPProcessor, CLIPModel
    loop = asyncio.get_event_loop()

    def _run():
        model = CLIPModel.from_pretrained(settings.vision_model)
        processor = CLIPProcessor.from_pretrained(settings.vision_model)
        image = Image.open(image_path).convert("RGB")
        inputs = processor(images=image, return_tensors="pt")
        with torch.no_grad():
            features = model.get_image_features(**inputs)
        vec = features[0].numpy()
        vec = vec / (vec ** 2).sum() ** 0.5
        return vec.tolist()

    return await loop.run_in_executor(None, _run)
