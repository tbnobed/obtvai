---
name: Archive date meaning
description: User-confirmed meaning of creation-date requests in the archive assistant.
---

Interpret requests such as “show me all media created in July 2025” as filtering by original air date.

**Why:** The user explicitly chose Original air date over archive-added date and source-file last-modified date. Visual similarity is not evidence of any date.

**How to apply:** Use original-air-date metadata and label the interpretation in answers. Exclude unknown dates instead of substituting ingest or filesystem dates. Explicit requests for different date fields must not be silently mapped to original air date.

Prioritize 2026 content for ingestion using original air date, not date added to Curator.

**Why:** The user explicitly selected “Originally aired in 2026” for ingestion priority.

**How to apply:** Rank eligible 2026 assets ahead of older or unknown-air-date assets without dropping the latter or bypassing existing eligibility, concurrency, and retry limits. Preserve in-flight work. Curator's field is `TBN_OriginalAirDate`; the Gateway accepts existence queries but rejected attempted Lucene-style date ranges, so use validated metadata rather than guessed search syntax.