---
name: Fish evaluation runtime
description: Dependency-resolution traps when evaluating Fish speech models in an isolated GPU runtime.
---

Installing SGLang Omni's Fish extras from PyPI does not automatically apply the upstream repository's uv dependency overrides.

**Why:** The audio-tools dependency declares an old protobuf ceiling that conflicts with the CUDA/CUTLASS runtime. Upstream explicitly overrides that ceiling; a normal extras installation can therefore fail even with the recommended container.

**How to apply:** Check the current upstream pyproject's override-dependencies and apply its compatible protobuf constraint explicitly in the isolated evaluation environment. Do not downgrade the live workers' packages to accommodate an audition. Verify real CUDA execution, not just successful imports, before reserving a worker for the test.
