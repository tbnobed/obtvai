---
name: Cross-asset person identification pitfalls
description: Lessons from debugging "missing people" in embedding-based speaker/face identity matching
---

# Person identification matching rules

- **Enforce distinct person per diarized speaker within one asset.** Two different diarized voices in the same video are never the same person; without this constraint, a single person record (especially one with blended/centroid embeddings) absorbs multiple real speakers and people "go missing".
  **Why:** blended embeddings from running-average updates act like centroids and match many voices even at strict thresholds (0.75 cosine).
  **How to apply:** track claimed person IDs per identify run and exclude them from matching for later speakers of the same asset.
- **Re-analysis must purge stale auto-created identities first.** Raising similarity thresholds does NOT fix people already over-merged under looser thresholds — their blended embeddings keep absorbing speakers on re-runs. Wipe auto-created (non-manually-named) people before a full re-analysis; keep manually named ones.
- **Face-only clusters must create people too** (with a quality gate, e.g. ≥5s on screen or ≥3 appearances), or anyone who appears on screen without speaking is silently dropped.
- Cosine thresholds that worked: 0.75 voice (pyannote), 0.70 face (FaceNet). 0.60 over-merges badly.
- Advisory-lock note: Postgres xact-level and session-level advisory locks share the same lock space, so an API endpoint using `pg_advisory_xact_lock(key)` correctly serializes against a worker holding `pg_advisory_lock(key)`.
