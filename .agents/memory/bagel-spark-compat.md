---
name: BAGEL on DGX Spark (GB10) CUDA compat pitfalls
description: Critical deployment constraints for running BAGEL-7B on the DGX Spark with R580 driver
---

## Rule
Use `nvcr.io/nvidia/pytorch:25.09-py3` as the base image for BAGEL on the DGX Spark — **never 25.12**.

**Why:** `25.12-py3` requires driver 590.44+ and relies on CUDA Forward Compatibility mode. Compat only activates on the very first container start. Every restart after that produces `ERROR: compatibility mode is UNAVAILABLE`, causing:
- `terminate called without an active exception` (C++ abort from CUDA ops in compat path)
- `ValueError: weight is on the meta device` (broken accelerate device-map dispatch)
- Each failed restart also fragments the CUDA virtual-address window, so `torch.cuda.mem_get_info()` reports decreasing free memory (8.4 → 15.7 → 6.9 → 2.8 GiB) even though physical memory (nvidia-smi) is unchanged.

`25.09-py3` uses CUDA 12.6 which the R580/580.x driver supports natively. No compat needed, restarts are reliable.

**How to apply:** Any time the BAGEL Dockerfile is modified or the base image is updated, verify the new tag is ≤25.09 (or whatever the cutoff is for native R580 support). Check NVIDIA's driver compatibility table: the container's required driver version must be ≤ the installed driver.

## Memory detection on GB10 (unified memory)
`torch.cuda.mem_get_info()` returns the CUDA virtual-address window assigned to the container context, NOT the full unified memory pool. On a Spark with vLLM at 88 GiB, it can return as little as 2-4 GiB even when 39+ GiB are physically free.

**Fix:** Set `BAGEL_MAX_MEMORY_GIB=30` in `.env` on the Spark (128 GiB total − 88 GiB vLLM − 10 GiB headroom). The server reads this env var first and skips all memory detection. Never rely on `mem_get_info()` on unified-memory hardware.

## Restart policy
`restart: unless-stopped` causes Docker to restart the container even after clean SIGTERM exits (exit code 0). Combined with the compat-breaks-on-restart problem, every manual `docker compose stop` triggers another broken start. Use `restart: on-failure:5` + `stop_grace_period: 120s`.

## Deployment checklist for the Spark
1. `docker compose down worker-bagel` (full remove, not stop)
2. Verify `nvidia-smi` shows only vLLM + Xorg (no stale Python processes)
3. Rebuild: `docker compose build worker-bagel`
4. Start once: `docker compose up -d worker-bagel`
5. Watch logs — load takes ~90s, model is ~30 GB
6. Health returns 200 OK → stable, do not restart
