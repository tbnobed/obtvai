"""
Local LLM inference using an instruction-tuned model (default: Qwen3 8B —
ungated on HuggingFace, no access approval required).
The model is configurable via the LLM_MODEL environment variable.

Loading mirrors the worker's analyze task (tokenizer + AutoModelForCausalLM +
chat template). dtype is chosen per device: half precision only on GPU —
fp16 weights on CPU produce "mat1 and mat2 must have the same dtype" errors.
"""
import asyncio
import os
import threading

LLM_MODEL = os.getenv("LLM_MODEL", "Qwen/Qwen3-8B")

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


_DEFAULT_SYSTEM = (
    "You are a sharp, analytical media librarian for a video archive. You answer "
    "questions about the library's video content using the provided transcript "
    "excerpts as evidence. Be direct and specific: quote or paraphrase relevant "
    "lines and reference their timecodes. Go beyond restating the excerpts — "
    "synthesize across them, identify themes and patterns, and draw reasonable "
    "conclusions, clearly framing interpretation as such (\"based on these "
    "excerpts, the pattern suggests...\"). Only say the material doesn't answer "
    "the question when there is genuinely nothing relevant to work with."
)


def _generate(
    prompt: str,
    max_new_tokens: int = 512,
    history: list[dict] | None = None,
    system: str | None = None,
) -> str:
    import torch
    tokenizer, model = _load_pipeline()
    messages = [{"role": "system", "content": system or _DEFAULT_SYSTEM}]
    for m in history or []:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": prompt})
    # enable_thinking=False: Qwen3 hybrid-reasoning models default to emitting
    # <think> blocks; disable for direct answers. Older templates ignore the kwarg.
    inputs = tokenizer.apply_chat_template(
        messages, add_generation_prompt=True, return_tensors="pt",
        enable_thinking=False,
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


async def generate_response(
    prompt: str,
    history: list[dict] | None = None,
    system: str | None = None,
    max_new_tokens: int = 512,
) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, lambda: _generate(prompt, max_new_tokens=max_new_tokens, history=history, system=system)
    )
