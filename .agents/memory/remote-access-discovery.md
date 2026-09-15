---
name: Remote access discovery
description: Recover existing production connection tooling before requesting connection details again.
---

Check ignored operational tooling as well as tracked files before asking for production connection details after context compaction.

**Why:** The existing SSH helper was in an ignored workspace directory, so ordinary repository searches missed it and led to unnecessary requests for information the user had already supplied.

**How to apply:** Include ignored operational directories in a targeted filename search. Reuse existing credential-redacting tooling rather than displaying credentials or requesting them again. Temporary known-host files may not survive workspace recreation; distinguish a missing trust file from an actual changed host key.