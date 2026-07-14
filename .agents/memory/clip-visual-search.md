---
name: CLIP visual search pitfalls
description: Why visual (CLIP) search returns uniform noise scores and how to keep the pipeline healthy
---

## Query and index must use the SAME CLIP model
**Why:** Different CLIP checkpoints (base-patch32 vs large-patch14) embed into unrelated spaces (and different dims). Comparing across them yields uniform noise-level cosine scores (~0.15-0.17) with no error.
**How to apply:** Any config default for the vision model must be identical in the API (query side) and worker (index side). Check both defaults, not just the env var.

## Scene keyframes must be representative, not midpoint grabs
**Why:** Textless broadcast masters and fades put black frames throughout scenes; a single midpoint frame grab embeds black frames -> all visual scores collapse to noise and thumbnails render black.
**How to apply:** Use ffmpeg `fps=2,thumbnail=N` over the scene span (histogram-based representative frame). Additionally skip near-black/uniform images before embedding (mean<10 or std<5 on a 64x64 downsample).

## Score bands differ across embedding families
**Why:** CLIP text->image cosine (~0.15-0.35) vs sentence-transformer text-text (~0.3-0.6). Merging raw scores buries all visual hits below the top-N cut.
**How to apply:** Rescale CLIP scores into a comparable 0-1 band before merging, and reserve result slots for visual hits in combined mode. Use "a photo of {query}" prompt template for CLIP text queries.
