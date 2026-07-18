---
name: pip resolver backtracking in worker image
description: How to handle hours-long pip backtracking during Docker builds of the ML worker
---

Rule: when the worker image's pip install backtracks for more than a few minutes, pin the transitive deps it's churning on (huggingface-hub, kombu/amqp/vine/billiard, grpcio, protobuf, torchcodec) to known-good versions rather than waiting.

**Why:** With ~30 top-level ML deps, pip's resolver can spend 90+ minutes exploring before surfacing a real conflict. Pinning collapses the search space so the true `ResolutionImpossible` cause appears in ~2 minutes (e.g. hidden pins: pyannote.audio 4.x hard-pins torch==2.8.0 and torchcodec==0.7.0; pyannote-metrics needs scikit-learn>=1.6.1; coqui-tts caps transformers per minor version — check requires_dist on PyPI per version before choosing).

**How to apply:** Conflicts only surface on full image rebuilds, not while old containers run — a pin added weeks ago can "suddenly" break a deploy. When adjusting torch, move torch/torchvision/torchaudio in lockstep (see torch-pinning.md) and verify each library's requires_dist via `https://pypi.org/pypi/<pkg>/<ver>/json`.
