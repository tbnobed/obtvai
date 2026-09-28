---
name: Archive search cost
description: Why unified Library search uses explicit submission instead of search-as-you-type.
---

Keep expensive archive search separate from draft text editing. Enter or Search commits a query; changes to its filters may rerun that committed query.

**Why:** Unlike the former filename-only filter, unified search requests can run GPU text/visual embeddings. Debouncing keystrokes still produces repeated inference work during pauses, and ignoring stale browser responses does not stop upstream inference.

**How to apply:** Preserve explicit submission when polishing the Library search experience. If adding live suggestions, use a cheap metadata-only path or a proven server-side cancellation and caching strategy rather than sending draft text to semantic search.