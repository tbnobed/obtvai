---
name: Blackwell NVENC ffmpeg requirement
description: NVENC ffmpeg build must match the NVIDIA driver branch; R580/CUDA-13 drivers need ffmpeg 8.x
---

**Rule:** NVENC on Blackwell GPUs (RTX 5090) is driver-version sensitive in BOTH directions. ffmpeg must be built against nv-codec-headers matching the installed driver branch: apt ffmpeg 4.4 is too old for Blackwell at all, and ffmpeg 7.1 (SDK 12.x headers) fails on R580+/CUDA-13 drivers with "OpenEncodeSessionEx failed: unsupported device (2)". R580-era drivers need ffmpeg 8.x (SDK 13 headers).

**Why:** NVIDIA driver branches drop old NVENC API generations; Blackwell + R580 removed the API level that ffmpeg 7.1 targets. The failure is silent if code has a libx264 CPU fallback — encodes appear to "work" but peg all CPU cores.

**How to apply:** Install a static BtbN build matching the driver (e.g. `ffmpeg-n8.1-latest-linux64-gpl-8.1.tar.xz` from BtbN/FFmpeg-Builds releases — check actual asset names via the GitHub API, version-guessed URLs 404) into /usr/local/bin so it shadows apt ffmpeg on PATH; keep the apt package for shared libs (torchaudio). Diagnose in order: `ffmpeg -version` (right build?), `nvidia-smi` in container (GPU visible?), testsrc encode with `-c:v h264_nvenc` in container, then the SAME binary on the host (`docker compose cp` it out).

**Container-only NVENC failure (host works, libs match):** bisect with a bare container before blaming caps or the base image: `docker run --rm --gpus all -e NVIDIA_DRIVER_CAPABILITIES=all -v /path/ffmpeg:/f:ro ubuntu:22.04 /f -f lavfi -i testsrc=duration=1:size=640x360:rate=30 -c:v h264_nvenc -f null -`, then per-index with `--gpus device=N`. NVENC support can differ PER GPU in a multi-GPU box: on driver 580.x an RTX 5090 rejected encode sessions ("unsupported device (2)") while an RTX PRO 6000 Blackwell in the same box encoded fine — CUDA worked on both, so only an actual encode attempt reveals which card works. Pin NVENC to the verified index. Also confirmed NOT culprits: ffmpeg SDK version (8.1 tested), driver capability set (once `all`), the CUDA base image's /usr/local/cuda/compat libs.
