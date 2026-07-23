"""OpenAI-compatible remote LLM client (e.g. vLLM on a DGX Spark).

Enabled by setting LLM_BASE_URL (e.g. http://192.168.101.1:8000/v1). When set,
AI Q&A, insights, and all creative/story prompts are served by the remote
endpoint instead of loading the local model into the media GPUs. Unset = fully
local, exactly as before.

Failures raise — there is deliberately NO silent fallback to the local model:
an unexpected 17 GB model load would starve ComfyUI and the media jobs of VRAM,
and a down Spark should be visible, not hidden.

This file is intentionally duplicated in services/api/app/services/ and
services/worker/tasks/ (separate Docker build contexts) — keep both identical.
"""
import os
import re
import threading

LLM_BASE_URL = (os.getenv("LLM_BASE_URL") or "").strip().rstrip("/")
LLM_API_KEY = (os.getenv("LLM_API_KEY") or "").strip()
_REMOTE_MODEL = (os.getenv("LLM_REMOTE_MODEL") or "").strip()

_model_cache: str | None = None
_model_lock = threading.Lock()


def remote_enabled() -> bool:
    return bool(LLM_BASE_URL)


def _resolve_model(client) -> str:
    """The model name to send: LLM_REMOTE_MODEL, or whatever the server serves."""
    global _model_cache
    if _REMOTE_MODEL:
        return _REMOTE_MODEL
    with _model_lock:
        if _model_cache:
            return _model_cache
        r = client.get(f"{LLM_BASE_URL}/models")
        r.raise_for_status()
        data = r.json().get("data") or []
        if not data:
            raise RuntimeError("Remote LLM: /v1/models returned no models")
        _model_cache = data[0]["id"]
        return _model_cache


def remote_chat(messages: list[dict], max_new_tokens: int = 512) -> str:
    """Send a chat completion to the remote server; returns the text answer."""
    import httpx

    headers = {"Authorization": f"Bearer {LLM_API_KEY}"} if LLM_API_KEY else {}
    timeout = httpx.Timeout(600.0, connect=10.0)
    try:
        with httpx.Client(timeout=timeout, headers=headers) as client:
            model = _resolve_model(client)
            r = client.post(
                f"{LLM_BASE_URL}/chat/completions",
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_new_tokens,
                    "temperature": 0,
                    # vLLM extension: Qwen3 hybrid-reasoning models default to
                    # <think> blocks; other servers ignore the field.
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            )
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        # Keep the message short and URL-free (never leak query params/keys).
        raise RuntimeError(
            f"Remote LLM at LLM_BASE_URL unreachable or failed: {type(e).__name__}: "
            f"{str(e)[:200]}"
        ) from e
    content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    # Belt and braces: strip reasoning blocks if the server emitted them anyway.
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
    return content.strip()
