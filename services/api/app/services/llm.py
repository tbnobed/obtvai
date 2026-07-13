"""
Local LLM inference using an instruction-tuned model (default: Qwen 2.5 7B Instruct —
ungated on HuggingFace, no access approval required).
The model is configurable via the LLM_MODEL environment variable.

Loading mirrors the worker's analyze task (tokenizer + AutoModelForCausalLM +
chat template). dtype is chosen per device: half precision only on GPU —
fp16 weights on CPU produce "mat1 and mat2 must have the same dtype" errors.
"""
import asyncio
import os
import threading

LLM_MODEL = os.getenv("LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct")

_llm = None  # (tokenizer, model)
_llm_lock = threading.Lock()


def _load_pipeline():
    global _llm
    if _llm is None:
        with _llm_lock:
            if _llm is None:
                import torch
                from transformers import AutoModelForCausalLM, AutoTokenizer
                tokenizer = AutoTokenizer.from_pretrained(LLM_MODEL)
                if torch.cuda.is_available():
                    model = AutoModelForCausalLM.from_pretrained(
                        LLM_MODEL,
                        torch_dtype=torch.bfloat16,
                        device_map={"": 0},
                    )
                else:
                    model = AutoModelForCausalLM.from_pretrained(
                        LLM_MODEL,
                        torch_dtype=torch.float32,
                    )
                model.eval()
                print(
                    f"LLM loaded: {LLM_MODEL} on {model.device} "
                    f"(dtype={next(model.parameters()).dtype})"
                )
                _llm = (tokenizer, model)
    return _llm


def _generate(prompt: str, max_new_tokens: int = 512) -> str:
    import torch
    tokenizer, model = _load_pipeline()
    messages = [
        {
            "role": "system",
            "content": (
                "You are a precise media analyst. You answer questions about video "
                "content using only the provided transcript excerpts. Be direct and "
                "specific: quote or paraphrase the relevant lines and reference their "
                "timecodes. If the excerpts do not contain the answer, say so plainly."
            ),
        },
        {"role": "user", "content": prompt},
    ]
    inputs = tokenizer.apply_chat_template(
        messages, add_generation_prompt=True, return_tensors="pt"
    ).to(model.device)
    attention_mask = torch.ones_like(inputs)
    with torch.no_grad():
        output_ids = model.generate(
            inputs,
            attention_mask=attention_mask,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            temperature=None,
            top_p=None,
            top_k=None,
            pad_token_id=tokenizer.eos_token_id,
        )
    return tokenizer.decode(output_ids[0][inputs.shape[1]:], skip_special_tokens=True).strip()


async def generate_response(prompt: str) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: _generate(prompt))
