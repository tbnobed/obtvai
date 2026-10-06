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

For unexpected outages, distinguish host boot history from container restart counts, and verify crash capture is actually armed before interpreting missing dumps.

**Why:** A Spark host reboot left Docker reporting zero container restarts. The installed crash-dump service was enabled but USE_KDUMP was disabled and no crash kernel was loaded. Missing crash records therefore could not distinguish power loss from a hard kernel failure.

**How to apply:** Correlate previous-boot journals with the AI server's physical-link history and historical memory samples. Do not use current memory or temperature to claim a past OOM or thermal shutdown, or treat a startup compatibility warning as a proven shutdown cause.

For unexplained GB10 hard power-offs, investigate power/SoC thermal behavior as well as driver failures; GPU temperature alone is insufficient. A temporary GPU clock cap is a diagnostic comparison, not a confirmed fix or proof of a defective adapter.

**Why:** Community reports describe abrupt power-offs without shutdown/crash records, including CPU/SoC temperatures substantially above GPU temperatures. Some report stability at a 2200 MHz clock cap. These are analogous reports, not a diagnosis of this unit: https://forums.developer.nvidia.com/t/hard-power-off-under-sustained-gpu-load-at-90w-persists-after-full-platform-firmware-update/378315 and https://forums.developer.nvidia.com/t/gb10-abruptly-powers-off-under-heavy-gpu-load-nvidia-smi-lgc-300-2200-prevents-it/384492 .

**How to apply:** Confirm physical power state when the DAC reports no partner; a lost link alone can also be a NIC/cable failure. After access returns, inspect firmware and capture all thermal zones, GPU clocks/power, and errors externally before a controlled workload comparison. Do not blindly apply forum firmware or power-limit commands.
