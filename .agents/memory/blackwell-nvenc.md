---
name: Blackwell NVENC ffmpeg requirement
description: RTX 50-series GPUs reject NVENC sessions from old ffmpeg builds; need ffmpeg >= 7.1
---

**Rule:** NVENC hardware encoding on Blackwell GPUs (RTX 5090, RTX PRO 6000) requires ffmpeg built against modern nv-codec-headers (ffmpeg >= 7.1). Older builds (Ubuntu 22.04 apt ffmpeg 4.4, Debian bookworm 5.1) fail to open encode sessions with "unsupported device", even when the container has GPU access and the `video` driver capability.

**Why:** Blackwell drivers dropped support for old NVENC SDK API versions. The failure is silent if code has a libx264 CPU fallback — encodes appear to "work" but peg all CPU cores.

**How to apply:** Install a static BtbN build (`ffmpeg-n7.1-latest-linux64-gpl-7.1.tar.xz` from BtbN/FFmpeg-Builds releases) into /usr/local/bin so it shadows apt ffmpeg on PATH; keep the apt package for shared libs (torchaudio). Container still needs `capabilities: [gpu, video]` + `NVIDIA_DRIVER_CAPABILITIES=compute,utility,video`. Verify with `ffmpeg -encoders | grep nvenc` and check job logs for which encoder actually succeeded.
