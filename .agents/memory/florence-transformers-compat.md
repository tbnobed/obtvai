---
name: Florence Transformers compatibility
description: Compatibility constraint between Florence-2 remote model code and Transformers attention selection.
---

Do not force `attn_implementation="sdpa"` when loading Microsoft Florence-2 through `trust_remote_code`.

**Why:** Florence's remote model class does not advertise Transformers' `_supports_sdpa` capability, so explicitly selecting SDPA fails during model construction with an attribute error before weights can load.

**How to apply:** Let Florence use its default/eager attention implementation. Avoid requiring FlashAttention; benchmark throughput using micro-batching instead.