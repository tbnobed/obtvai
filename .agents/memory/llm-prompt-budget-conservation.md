---
name: LLM prompt-budget conservation
description: When batching items into LLM prompts under a size cap, never silently drop what doesn't fit
---

Rule: any LLM pass that assembles items into a capped prompt (char/token budget) must account for every input item — either chunk the input so all items get reviewed, or carry unseen/skipped items through unchanged. A `break` at the size cap silently discards the tail.

**Why:** the reel story-editor pass capped candidate blocks at 14k chars and broke out of the loop — for a 432-candidate long-form reel only ~30 clips were curated and the rest passed through only because curation returned early; when a valid selection WAS returned, everything past the cap vanished from the output.

**How to apply:** chunk into fixed-size batches for full review; inside a batch, track included vs leftover items and append leftover raw to the result. Also: keep the prompt's candidate index parallel to the actual lookup list (items skipped for missing data shift indices — label blocks by the compacted list index, not the enumerate index).
