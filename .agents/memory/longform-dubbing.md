---
name: Long-form dubbing/translation pitfalls
description: Why long-form dubs drift, voices flip, and translations degrade — and the fixes now in the worker
---
- Drift mechanism: placement is absolute-start BUT `offset = max(start, place_cursor)` — overlong translated clips spill forward and compound in dense dialogue. Fix: max-lateness budget (DUB_MAX_LATENESS, 1.5s) → force-fit (atempo up to 1.6, tail trim w/ fade); if no room before next segment, drop the late clip — dropping one clip re-anchors, squeezing pushes lag onto everything after.
- Voice flip-flop: per-segment engine fallback (Chatterbox→XTTS) changes the voice mid-show. Rule: retry once, and after 3 failed segments switch the REST of the job — one engine boundary, never per-segment flips.
- Translation "garbage" on long form is NOT LLM context overflow — MADLAD is per-segment MT with zero context. Fix: remote-LLM path (TRANSLATE_USE_LLM, on when LLM_BASE_URL set): glossary pre-pass pins names/terms, batches ≤40 segs/6k chars with rolling 3-line tail, strict N-in/N-out JSON contract (violations → split-in-half retry → MADLAD fallback per batch). Blank segments must be persisted as "" outside the contract or they sink their whole batch.
- Resume: translation skips segments already having the target (full set = intentional redo); dub caches per-segment clips as .npy under DUBS_DIR/.work_<media>_<lang>, keyed by text+engine+speaker+voice-fingerprint (paths+mtimes+settings) — cache under the engine that ACTUALLY synthesized, hit only on the intended engine.
**Why:** all three long-form failure modes confirmed on production content Aug 2026; short content masks them.
