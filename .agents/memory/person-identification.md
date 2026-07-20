---
name: Cross-asset person identification pitfalls
description: Lessons from debugging "missing people" in embedding-based speaker/face identity matching
---

# Person identification matching rules

- **Enforce distinct person per diarized speaker within one asset.** Two different diarized voices in the same video are never the same person; without this constraint, a single person record (especially one with blended/centroid embeddings) absorbs multiple real speakers and people "go missing".
  **Why:** blended embeddings from running-average updates act like centroids and match many voices even at strict thresholds (0.75 cosine).
  **How to apply:** track claimed person IDs per identify run and exclude them from matching for later speakers of the same asset.
- **Weight embedding blends by prior appearance count (capped ~20), never 50/50.** A mega-cluster person (e.g. 41 assets absorbing a wrong-gender voice) forms because an equal-weight running average lets ONE bad match shift an established identity's embedding 50%, turning it into a centroid that passes 0.75 for everyone.
  **Why:** drift compounds — each wrong absorption makes the next more likely.
  **How to apply:** blend = (old*w + new)/(w+1), w = clamp(prior appearances, 1, 20); floor w (~5) for manually named people whose appearance rows were wiped but embeddings kept.
- **Cross-check modalities before accepting a match.** Veto a voice match when both sides have faces and face sim is contradiction-low (ArcFace < 0.15); veto a face match when both sides have voices and voice sim < 0.2 (face clusters can attach to the wrong on-screen speaker). A vetoed match creating a duplicate person is strictly better than a poisoned embedding — duplicates are user-mergeable.
- **Re-analysis must purge stale auto-created identities first.** Raising similarity thresholds does NOT fix people already over-merged under looser thresholds — their blended embeddings keep absorbing speakers on re-runs. Wipe auto-created (non-manually-named) people before a full re-analysis; keep manually named ones.
- **Face-only clusters must create people too** (with a quality gate, e.g. ≥5s on screen or ≥3 appearances), or anyone who appears on screen without speaking is silently dropped.
- Cosine thresholds that worked: 0.75 voice (pyannote). Face is embedder-specific: 0.55 ArcFace (current stack); 0.70 was the old FaceNet value. 0.60 FaceNet over-merges badly.
- **Assign speaker↔person matches globally, never per-speaker greedy in arbitrary order.** With exclusive claiming, whichever speaker is processed first steals a person that a later speaker matches more strongly, cascading a full one-slot identity rotation across the video (A gets B's name, B gets C's...). Wiping the people table does NOT fix this — the rotation re-forms during rebuild.
  **Why:** speaker iteration order comes from an unordered SQL GROUP BY; first-come-first-served + exclusivity makes match outcomes order-dependent.
  **How to apply:** score all speaker↔person pairs first, rank by margin above threshold normalized as (sim−thr)/(1−thr) so voice/face ranks are comparable, sort descending, then claim greedily with speaker+person exclusivity. Keep voice primary within a speaker (face candidates only when no voice match). If rotations recur, bias voice ranks above face ranks across speakers.
- **Floor the blend weight for near-new people (~3), not just manual ones.** w=1 for a 1-appearance person means its print shifts 50% on the very next match, so one early cross-match re-poisons a freshly rebuilt identity immediately; floor caps any single asset's shift at ≤25%.
- **Sample multiple frames per scene for face detection.** One frame (the scene thumbnail) misses most people in multi-person talk-show scenes. ~4 frames/scene (one per ~4s, capped per asset) via cv2.VideoCapture on the proxy fixes recall.
- DBSCAN on FaceNet embeddings: eps is cosine DISTANCE, not similarity — eps=0.6 means sim 0.4 and merges different people; eps≈0.30 (sim 0.7) is right.
- MTCNN at prob 0.90 passes hands/necks/graphics as faces. Need prob ≥0.98 PLUS landmark geometry gates (eyes above nose above mouth, landmarks inside box, eye distance ≥0.2× box width, aspect ratio 0.5–1.25) to keep People thumbnails clean.
- Per-asset derived tables (face_clusters etc.) must DELETE-then-insert on re-runs or they accumulate duplicates; also re-queue identify even when zero results so stale links get rebuilt.
- Advisory-lock note: Postgres xact-level and session-level advisory locks share the same lock space, so an API endpoint using `pg_advisory_xact_lock(key)` correctly serializes against a worker holding `pg_advisory_lock(key)`.
- **Photo enrollment must use the exact same face stack as the worker** (insightface buffalo_l, `normed_embedding`) or photo-vs-library similarities are meaningless. CPU providers in the API are fine for single photos. Photo-vs-video-frame sims run slightly lower than frame-vs-frame — "strong match" threshold 0.50 vs the worker's 0.55 cluster threshold.
- insightface is source-only with a Cython extension: any image that pip-installs it needs **g++**, not just gcc (worker Dockerfile has it; API Dockerfile needed it added).
