---
name: onnxruntime CPU wheel shadows GPU
description: Why plain onnxruntime must never coexist with onnxruntime-gpu in the worker image
---
Both packages install the same `onnxruntime` python module; whichever wheel lands last wins, and the plain CPU wheel silently removes CUDAExecutionProvider.

**Why:** InsightFace face detection ran on CPU in production (nvidia-smi showed 0% GPU during a lip-sync pass that took >4x realtime) because requirements.txt pinned both `onnxruntime` and `onnxruntime-gpu`.

**How to apply:** keep only `onnxruntime-gpu` in GPU images. To verify at runtime: `session.get_providers()` must include CUDAExecutionProvider — log it at pipeline start so the fallback is visible in job logs, not silent.

**Second failure mode (same symptom):** even with only onnxruntime-gpu installed, the CUDA provider fails to init when cuDNN/cuBLAS come from pip nvidia-* wheels (they sit in site-packages, off the loader path). Fix: onnxruntime-gpu>=1.22 and call `ort.preload_dlls()` before creating any session.
