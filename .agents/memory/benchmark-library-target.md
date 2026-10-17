---
name: Benchmark library target
description: User-selected ingestion stopping point and purpose.
---

Stop catalog ingestion at 10,000 total ready library assets, across media types,
not at 10,000 automatic-catalog completions or videos.

**Why:** The user explicitly selected total ready assets for a benchmark dataset
to decide whether a larger CPU server is necessary.

**How to apply:** Account for outstanding work, let jobs finish, and preserve the
stop independently of remote-model auto-recovery. Do not resume beyond the target
without a new instruction. Changing the second server's GPU role is separate work.
