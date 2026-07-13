"""
Local LLM inference using an instruction-tuned model (default: Qwen 2.5 7B Instruct —
ungated on HuggingFace, no access approval required).
The model is configurable via the LLM_MODEL environment variable.
"""
import asyncio
import os
import threading

LLM_MODEL = os.getenv("LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct")

_pipeline = None
_pipeline_lock = threading.Lock()


def _load_pipeline():
    global _pipeline
    if _pipeline is None:
        with _pipeline_lock:
            if _pipeline is None:
                from transformers import pipeline as hf_pipeline
                import torch
                _pipeline = hf_pipeline(
                    "text-generation",
                    model=LLM_MODEL,
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
