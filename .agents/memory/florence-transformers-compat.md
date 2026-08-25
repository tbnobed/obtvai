---
name: Florence Transformers compatibility
description: Compatibility constraint between Florence-2 remote model code and Transformers attention selection.
---

Explicitly force eager attention and disable generation caching when loading Microsoft Florence-2 through `trust_remote_code`.

**Why:** Florence's remote model class does not advertise Transformers' `_supports_sdpa` capability. Explicit SDPA fails, and recent Transformers versions may auto-select it. Its generation code also assumes legacy populated KV-cache tuples, while newer Transformers can pass an uninitialized cache entry and crash on `past_key_values[0][0].shape`.

**How to apply:** Pass the eager implementation explicitly and call `generate` with caching disabled. Avoid requiring FlashAttention; recover throughput with image micro-batching and short outputs.