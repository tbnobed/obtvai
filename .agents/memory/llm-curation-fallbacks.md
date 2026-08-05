---
name: LLM curation fallbacks
description: Distinguish "LLM response unusable" from "LLM deliberately selected little/nothing" in curation passes.
---
Rule: when an LLM curation/selection pass returns a *valid* response with a small or empty selection, honor it. Only fall back to raw candidates when the response is unusable (parse failure, no `clips` array). Signal deliberate-empty as `[]`, failure as `None`, and check `is not None` at every caller — truthiness checks (`if curated:`) silently treat both the same.

**Why:** a "keep at least 3 clips" sanity fallback kept resurrecting the exact content a user's brief excluded ("do not mention X" on material that was all X), making prompts look ignored no matter what.

**How to apply:** any pipeline where an LLM filters candidates (reel curation, clip selection, moment picking): valid-but-empty → propagate to a user-facing "nothing matches the brief" error, never to the un-filtered input. Also state exclusions explicitly in the LLM prompt and don't force a minimum keep count.
