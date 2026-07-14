---
name: Blackwell NVENC ffmpeg requirement
description: NVENC ffmpeg build must match the NVIDIA driver branch; R580/CUDA-13 drivers need ffmpeg 8.x
---

**Rule:** NVENC on Blackwell GPUs (RTX 5090) is driver-version sensitive in BOTH directions. ffmpeg must be built against nv-codec-headers matching the installed driver branch: apt ffmpeg 4.4 is too old for Blackwell at all, and ffmpeg 7.1 (SDK 12.x headers) fails on R580+/CUDA-13 drivers with "OpenEncodeSessionEx failed: unsupported device (2)". R580-era drivers need ffmpeg 8.x (SDK 13 headers).

**Why:** NVIDIA driver branches drop old NVENC API generations; Blackwell + R580 removed the API level that ffmpeg 7.1 targets. The failure is silent if code has a libx264 CPU fallback — encodes appear to "work" but peg all CPU cores.

**How to apply:** Install a static BtbN build matching the driver (e.g. `ffmpeg-n8.1-latest-linux64-gpl-8.1.tar.xz` from BtbN/FFmpeg-Builds releases — check actual asset names via the GitHub API, version-guessed URLs 404) into /usr/local/bin so it shadows apt ffmpeg on PATH; keep the apt package for shared libs (torchaudio). Diagnose in order: `ffmpeg -version` (right build?), `nvidia-smi` in container (GPU visible?), testsrc encode with `-c:v h264_nvenc` in container, then the SAME binary on the host (`docker compose cp` it out).

**Container-only NVENC failure (host works, libs match):** bisect with a bare container before blaming caps or the base image: `docker run --rm --gpus all -e NVIDIA_DRIVER_CAPABILITIES=all -v /path/ffmpeg:/f:ro ubuntu:22.04 /f -f lavfi -i testsrc=duration=1:size=640x360:rate=30 -c:v h264_nvenc -f null -`. If `--gpus all` works but `--gpus device=N` fails, the pinned index maps to a stale /dev/nvidiaN node (card re-slot / driver update leaves dead nodes). nvidia-smi STILL shows the GPU in that container (it uses the control node) and won't reveal the problem — only an actual encode attempt does. Fix: pin the device index of the live node (check `nvidia-smi -L`, `ls -l /dev/nvidia*` timestamps) or use a GPU UUID instead of an index. The CUDA base image's /usr/local/cuda/compat libs were NOT the culprit (tested).
