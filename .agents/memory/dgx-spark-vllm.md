---
name: DGX Spark vLLM serving
description: Getting NVIDIA's vLLM container running on a DGX Spark (GB10, unified memory)
---
Historically tested setup: `nvcr.io/nvidia/vllm:25.12.post1-py3` serving Qwen3-32B-AWQ, host port 8001 (8000 is taken by a stock service on the Spark). Inspect the current container before assuming its model or compatibility.

- The nvcr.io/nvidia/vllm repo has NO `latest` tag — only dated tags (25.09-py3 … 26.06-py3). Pick by driver branch.
- Container/driver matching must be verified from the running image and startup logs, not inferred from the vLLM version string. A container reporting nv25.12.post1 explicitly required driver 590.44+ and said compatibility mode was unavailable on 580.126.09.
- Spark memory is UNIFIED (120 GB shared with OS): vLLM's default `--gpu-memory-utilization 0.9` computes off total and fails "free memory less than desired". Use ~0.65 plus `--max-model-len 32768`.
- ~12 tok/s generation for 32B AWQ on GB10 — fine for Q&A, budget minutes for long story prompts.
**How to apply:** full run cmd lives in the chat/replit.md context; verify with `curl http://<spark>:8001/v1/models` from the client box before debugging app code.

**Why:** The later GPT-OSS-120B deployment loaded checkpoint shards despite a driver compatibility error. Docker “running,” GPU allocations, and weight-loading progress do not establish inference readiness.

**How to apply:** Allow progressing checkpoint loading to finish without repeated restarts, then require a real completion request before clearing the catalog pause. Match image/driver support if initialization or generation fails; do not dismiss explicit compatibility errors based on an older successful setup.
