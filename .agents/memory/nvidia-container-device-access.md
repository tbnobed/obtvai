---
name: NVIDIA container device access
description: Misleading Whisper OOM after systemd reload removes Docker GPU device permissions.
---

Check fresh-process GPU access inside a worker before attributing Whisper OOM to exhausted VRAM.

**Why:** After a service-manager reload on the rebuilt ingestion host, host NVIDIA diagnostics still worked and initialized workers still completed some GPU tasks, but fresh processes reported NVML Unknown Error or no CUDA devices. Whisper model loads reported CUDA OOM despite roughly 30 GiB free. Explicit Docker device mappings plus container recreation restored access and survived a reload test.

**How to apply:** Compare host and container diagnostics. Preserve explicit per-card NVIDIA device mappings when regenerating Compose, resolving minors from UUIDs. Drain workers before recreation; don't change model precision or retry completed assets as a substitute. Validate real speech decoding after a controlled reload, not an empty VAD sample.
