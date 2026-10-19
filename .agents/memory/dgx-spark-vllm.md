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

**Why:** NVIDIA moderator Neill acknowledges multiple thermal/current shutdown patterns and recommends a temporary 300–2100 MHz clock range as mitigation, not a root-cause fix: https://forums.developer.nvidia.com/t/spark-abruptly-shuts-down/377478/30 . Other posts report diagnostic failures and replacements, while some intermittently failing units pass diagnostics. This is analogous evidence, not a diagnosis of this unit.

**How to apply:** Confirm physical power state when the DAC reports no partner; a lost link alone can also be a NIC/cable failure. After access returns, inspect firmware and capture all thermal zones, GPU clocks/power, and errors externally before a controlled workload comparison. Do not blindly apply forum firmware or power-limit commands.

Clock caps do not persist through reboot; verify actual clock steps after applying. Field diagnostics are disruptive, not a routine live-server health check: the official guide requires GPU availability and Secure Boot disabled, with re-enabling afterward. Obtain approval before interrupting inference or changing boot security. https://docs.nvidia.com/dgx/dgx-spark/support.html#field-diagnostic-software

After a clock-cap command succeeds, allow the clock to settle before deciding it failed. An immediate query can still show the old frequency; 2100 MHz settled to the supported 2093 MHz step.

**Why:** The immediate readback exceeded the requested cap, while the subsequent readback confirmed it without reapplying or changing settings.

Docker log absence is not proof that a container produced no error after a hard outage.

**Why:** A malformed json-file log record caused Docker to report a decoding error and hide earlier vLLM startup failures. A bounded read of the raw log, parsing valid JSON records independently, recovered the actual CUDA initialization exception.

**How to apply:** When container restart events conflict with apparently empty error logs, check the Docker daemon journal for log-decoding errors. Read only a bounded tail of the inspected container LogPath, skipping invalid records; do not truncate or delete the evidence.

The user says the DGX has no visible lights or fans for them to check.

Treat GPU clock mitigation as temporary unless it has been verified after a
host reboot. A prior successful nvidia-smi lock does not establish boot-time
protection.

The user requested that the Spark's 2100-MHz GPU cap persist across reboots.
Keep the cap in place unless they authorize removing it.

**Why:** The user selected persistent containment after repeated host outages;
this remains a diagnostic mitigation, not evidence of a repaired power or
thermal fault.

**Why:** During a later repeated-host-outage investigation, live GPU clocks
exceeded the previously requested cap and there was no persistent cap service.
That proves mitigation was absent, not that its absence caused every outage.

**How to apply:** If restoring the mitigation is authorized, persist it before
model startup and verify delayed readback. Keep thermal/power versus kernel
failure hypotheses separate until externally recorded evidence distinguishes them.

Renew a bounded health recorder's restricted SSH-key expiration together with
its recording deadline; verify a successful telemetry sample, not just a live
recorder process.

**Why:** The original recording window and forced-command key both expired.
Restarting the recorder alone captured ping but SSH telemetry was refused by
key options.

**How to apply:** Extend only the existing health key's expiration, preserve
source/forced-command restrictions, and verify telemetry exit status and sample
timestamp before calling recording active.

On October 6, 2026, the user reported the DGX was extremely hot to the touch and moved it to an area with better airflow, requesting removal of the temporary cap to test stability.

**Why:** This is user-observed evidence relevant to cooling, not confirmation that thermal protection caused earlier shutdowns.

**How to apply:** Account for the changed physical placement when comparing stability; do not present the airflow change as a proven fix.

**Why:** Physical indicator checks are not available to distinguish off versus hung on this installation.

**How to apply:** Use boot history, both network paths, and whether someone manually powered it on. Do not repeatedly request light/fan observations.
