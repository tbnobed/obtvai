---
name: No-op guards need copied baselines
description: Change-detection guards silently disable features when mutation aliases the baseline
---
Rule: any "did anything change?" guard must compare against a deep-ish copy taken BEFORE mutation. If the new state is built from the same dict/list objects as the baseline (`[c for c in cut]`), in-place edits mutate both sides and the comparison is always "unchanged."
**Why:** a no-op guard in the cut-adjust path aliased the clip dicts; every resize was detected as "no change," so the whole equal-clip-length feature silently did nothing while replying "the cut is already fine."
**How to apply:** when adding no-op/idempotence checks, snapshot `[dict(c) for c in items]` (or tuples of key fields) first; write a quick identity test that a known mutation is detected as a change.
