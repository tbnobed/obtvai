---
name: Remote LLM offload
description: LLM_BASE_URL routes all LLM inference to an OpenAI-compatible server; gating rules
---
Rule: when adding a remote-inference switch, gate EVERY local load site — not just the generate path. The API had a startup warm-up thread that loaded the LLM unconditionally; architect caught it defeating the whole VRAM-saving goal.
**Why:** load sites are scattered (request path, warm-up threads, direct `_load_llm()` callers); missing one silently reloads 17 GB onto shared GPUs.
**How to apply:** grep for every `_load_pipeline`/`_load_llm` call before shipping; remote mode returns (None,None) from loaders so opaque tokenizer/model pass-through keeps all callers working. Qwen3 remote needs `chat_template_kwargs: {enable_thinking: false}` (vLLM) plus a `<think>` strip as fallback. No silent local fallback on remote failure — a down endpoint must be visible.
