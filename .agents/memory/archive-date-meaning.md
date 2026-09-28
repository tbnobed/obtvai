---
name: Archive date meaning
description: User-confirmed meaning of creation-date requests in the archive assistant.
---

Interpret requests such as “show me all media created in July 2025” as filtering by original air date.

**Why:** The user explicitly chose Original air date over archive-added date and source-file last-modified date. Visual similarity is not evidence of any date.

**How to apply:** Use original-air-date metadata and label the interpretation in answers. Exclude unknown dates instead of substituting ingest or filesystem dates. Explicit requests for different date fields must not be silently mapped to original air date.