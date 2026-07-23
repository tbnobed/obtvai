"""
Local LLM inference using an instruction-tuned model (default: Qwen3 8B —
ungated on HuggingFace, no access approval required).
The model is configurable via the LLM_MODEL environment variable.

Loading mirrors the worker's analyze task (tokenizer + AutoModelForCausalLM +
chat template). dtype is chosen per device: half precision only on GPU —
fp16 weights on CPU produce "mat1 and mat2 must have the same dtype" errors.
"""
import asyncio
import gc
import os
import threading
import time

LLM_MODEL = os.getenv("LLM_MODEL", "Qwen/Qwen3-8B")

# Drop the model from VRAM after this many seconds without a request, so
# ComfyUI and the GPU workers (which share the card) get the memory back
# between Q&A sessions. 0 disables. Reload takes ~30-60 s from local cache.
_IDLE_SECONDS = int(os.getenv("GPU_IDLE_RELEASE_SECONDS", "300") or "0")

_llm = None  # (tokenizer, model)
_llm_lock = threading.Lock()
_active = 0  # in-flight generations (guarded by _llm_lock)
_last_used = time.monotonic()
_watchdog_started = False


def _free_cuda():
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def _idle_watchdog():
    global _llm
    while True:
        time.sleep(30)
        with _llm_lock:
            release = (
                _llm is not None
                and _active == 0
                and (time.monotonic() - _last_used) >= _IDLE_SECONDS
            )
            if release:
                _llm = None
        if release:
            _free_cuda()
            print(f"LLM released from VRAM after {_IDLE_SECONDS}s idle")


def _load_pipeline():
    global _llm, _watchdog_started
    if _IDLE_SECONDS > 0:
        with _llm_lock:
            if not _watchdog_started:
                _watchdog_started = True
                threading.Thread(
                    target=_idle_watchdog, daemon=True, name="llm-idle-release"
                ).start()
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
    "conclusions, making clear when something is your interpretation rather than "
    "a direct statement. Only say the material doesn't answer the question when "
    "there is genuinely nothing relevant to work with. Start your answer with "
    "the substance itself — never open with boilerplate like \"Based on the "
    "provided transcript excerpts\". Write in plain text without markdown "
    "formatting such as ** or #."
)


def _generate(
    prompt: str,
    max_new_tokens: int = 512,
    history: list[dict] | None = None,
    system: str | None = None,
) -> str:
    global _active, _last_used
    with _llm_lock:
        _active += 1
    try:
        return _generate_inner(
            prompt, max_new_tokens=max_new_tokens, history=history, system=system
        )
    finally:
        with _llm_lock:
            _active -= 1
            _last_used = time.monotonic()


def _generate_inner(
    prompt: str,
    max_new_tokens: int = 512,
    history: list[dict] | None = None,
    system: str | None = None,
) -> str:
    messages = [{"role": "system", "content": system or _DEFAULT_SYSTEM}]
    for m in history or []:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": prompt})
    from app.services.llm_remote import remote_enabled, remote_chat
    if remote_enabled():
        # Remote inference (LLM_BASE_URL, e.g. vLLM on the DGX Spark): the
        # local model is never loaded, keeping the media GPUs free.
        return remote_chat(messages, max_new_tokens=max_new_tokens)
    import torch
    tokenizer, model = _load_pipeline()
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
