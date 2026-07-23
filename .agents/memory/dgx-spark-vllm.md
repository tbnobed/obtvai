---
name: DGX Spark vLLM serving
description: Getting NVIDIA's vLLM container running on a DGX Spark (GB10, unified memory)
---
Working setup: `nvcr.io/nvidia/vllm:25.12.post1-py3` serving Qwen3-32B-AWQ, host port 8001 (8000 is taken by a stock service on the Spark).

- The nvcr.io/nvidia/vllm repo has NO `latest` tag — only dated tags (25.09-py3 … 26.06-py3). Pick by driver branch.
- Container/driver matching: 26.06 requires driver 610.43+; the Spark ships R580 (580.126.09) → use 25.12.post1 (forward-compat mode makes it work). Same lesson as Blackwell NVENC: match the release to the driver branch.
- Spark memory is UNIFIED (120 GB shared with OS): vLLM's default `--gpu-memory-utilization 0.9` computes off total and fails "free memory less than desired". Use ~0.65 plus `--max-model-len 32768`.
- ~12 tok/s generation for 32B AWQ on GB10 — fine for Q&A, budget minutes for long story prompts.
**How to apply:** full run cmd lives in the chat/replit.md context; verify with `curl http://<spark>:8001/v1/models` from the client box before debugging app code.
