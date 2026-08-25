---
name: Florence Transformers compatibility
description: Compatibility constraint between Florence-2 remote model code and Transformers attention selection.
---

Explicitly force `attn_implementation="eager"` when loading Microsoft Florence-2 through `trust_remote_code`.

**Why:** Florence's remote model class does not advertise Transformers' `_supports_sdpa` capability. Explicit SDPA fails, and recent Transformers versions may auto-select SDPA even when no implementation is passed, producing the same attribute error before weights load.

**How to apply:** Pass the eager implementation explicitly. Avoid requiring FlashAttention; benchmark throughput using micro-batching instead.