"""
Local LLM inference using an instruction-tuned model (default: Llama 3.2 3B Instruct).
The model is configurable via the LLM_MODEL environment variable.
"""
import asyncio
import os

LLM_MODEL = os.getenv("LLM_MODEL", "meta-llama/Llama-3.2-3B-Instruct")

_pipeline = None


def _load_pipeline():
    global _pipeline
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
