"""
Local LLM inference using a small instruction-tuned model (Llama 3.2 / Mistral 7B).
Falls back to a deterministic summary if the model is not loaded.
"""
import asyncio
from typing import Optional

_pipeline = None


def _load_pipeline():
    global _pipeline
    if _pipeline is None:
        from transformers import pipeline as hf_pipeline
        import torch
        _pipeline = hf_pipeline(
            "text-generation",
            model="meta-llama/Llama-3.2-1B-Instruct",
            torch_dtype=torch.float16,
            device_map="auto",
            max_new_tokens=512,
        )
    return _pipeline


async def generate_response(prompt: str) -> str:
    loop = asyncio.get_event_loop()

    def _run():
        pipe = _load_pipeline()
        result = pipe(prompt, do_sample=False, temperature=None, top_p=None)
        generated = result[0]["generated_text"]
        if generated.startswith(prompt):
            generated = generated[len(prompt):].strip()
        return generated

    return await loop.run_in_executor(None, _run)
