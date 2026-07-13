---
name: Torch stack pinning
description: Why torch, torchvision, and torchaudio must be pinned together in worker requirements
---
Rule: in GPU worker requirements, pin torch, torchvision, AND torchaudio to the same matching release with the same CUDA suffix (e.g. 2.7.1+cu128 / 0.22.1+cu128 / 2.7.1+cu128).

**Why:** torchaudio/torchvision are compiled against an exact torch ABI. If any one is unpinned, a Docker rebuild resolves the latest wheel (often pulled in transitively, e.g. pyannote.audio → torchaudio) and imports fail at runtime with `undefined symbol: torch_library_impl`-style errors.

**How to apply:** whenever bumping torch, bump torchvision/torchaudio to their matching versions from the same PyTorch release, keeping the `--extra-index-url .../whl/cu128` line consistent.
