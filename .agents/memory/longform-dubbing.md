---
name: Long-form dubbing/translation pitfalls
description: Why long-form dubs drift, voices flip, and translations degrade — and the fixes now in the worker
---
- Drift policy: preserve complete speech while bounding lateness. Never drop a segment or trim spoken tails to recover synchronization; if bounded pitch-preserving acceleration cannot fit it, fail explicitly with the affected timestamp.
  **Why:** Dropping dialogue produced a superficially successful but incomplete production dub. A clear timing failure is preferable to publishing missing words.
  **How to apply:** Fit before placement against the next cue's lateness budget and video end; require shorter translated text or corrected timestamps when it cannot fit.
  Natural pacing takes precedence over forcing a job to succeed. Do not restore a 2x–2.5x emergency speed ceiling.
  **Why:** The user rejected the resulting fast speech even though jobs succeeded and files decoded correctly. Those checks did not establish acceptable listening quality.
  **How to apply:** Use modest acceleration only, regenerate bad synthesis, then try duration-aware equivalent wording with a separate meaning check. Flag impossible segments for review; never claim a natural-sounding delivery based only on job status or decoding.
- Voice consistency: do not switch engines mid-dub, including after repeated failures. Audit missing speaker profiles as well as engine-error fallbacks; a requested cloned dub must not be described as fully cloned when some speakers use stock voices.
  **Why:** The user reported changing accents and a hallway-like echo within the Spanish dub after the pacing correction. Successful synthesis, decoding, and speech-recognition checks did not establish voice or acoustic consistency.
  **How to apply:** Verify speaker/profile coverage before a full regeneration, keep a fixed reference and engine per actual speaker, and evaluate a short opening sample for accent and room sound. Do not attribute audible echo to a reference recording without checking it, or claim listening verification from ASR.
- Timing must repay accumulated delay by targeting the next cue from the actual placement cursor, not repeatedly spending the entire lateness allowance. Before rejecting a cue, bounded unoccupied lead-in may be used (same budget as lateness), never overlapping prior speech; disclose that shift in job logs.
  **Why:** Dense sentences accumulated avoidable delay until otherwise short phrases failed. A separately verified 22-second source really contained its only sentence in the final 1.24 seconds; its complete Spanish speech fit using 0.95 seconds of vacant lead-in without raising the acceleration ceiling.
  **How to apply:** Preserve the no-word-trimming/no-overlap rules and end-of-video bound. Check both accumulated-delay cases and end-of-video cases with actual FFmpeg audio, not only mocked sample counts.
- Transcript cue boundaries are not necessarily speech phrase boundaries. Give connected same-speaker phrases shared timing rather than rejecting each tiny fragment separately.
  **Why:** Individually synthesizing fragments adds pauses and puts short closing phrases into artificially impossible windows. The user explicitly rejected merely lowering the speed limit and returning failed jobs as a fix.
  **How to apply:** Preserve speaker changes and real pauses, bound synthesis length, keep source/translation context aligned across grouped cues, and verify regenerated audio rather than treating a guardrail as the deliverable.
- Reclaim unused time behind preceding phrases before rejecting the current one. Plan backward shifts transactionally within the same sync budget; update both waveform placement and lip-sync spans.
  **Why:** A locally greedy scheduler could consume the following phrase's allowance despite usable space earlier, producing artificial timing failures at natural speed.
  **How to apply:** Never overlap speech or exceed phrase bounds. Keep accepted duration adaptations across retries so a later failure cannot randomly undo an already verified correction.
- Budget reasoning-model tokens for both translation adaptation and its meaning check.
  **Why:** Small output limits yielded empty content after internal reasoning, causing JSON failures instead of usable adaptation. A short expected JSON answer does not imply a small total completion budget.
  **How to apply:** Treat malformed/empty answers as retryable model failures with bounded retries, not evidence that faithful wording cannot fit.
- Give duration adaptation a concrete spoken-word budget and carry the rejected draft alongside the review feedback.
  **Why:** A seconds-only request repeatedly produced overlong Spanish or omitted qualifiers such as time of day. Feedback without the rejected wording could repeat the same omission.
  **How to apply:** Use a conservative word-rate estimate, verify actual synthesized duration, and independently check meaning against the source. Preserve dates, named entities and qualifiers; never use faster playback to conceal failure.
- Translation "garbage" on long form is NOT LLM context overflow — MADLAD is per-segment MT with zero context. Fix: remote-LLM path (TRANSLATE_USE_LLM, on when LLM_BASE_URL set): glossary pre-pass pins names/terms, batches ≤40 segs/6k chars with rolling 3-line tail, strict N-in/N-out JSON contract (violations → split-in-half retry → MADLAD fallback per batch). Blank segments must be persisted as "" outside the contract or they sink their whole batch.
- Resume: translation skips segments already having the target (full set = intentional redo); dub caches per-segment clips as .npy under DUBS_DIR/.work_<media>_<lang>, keyed by text+engine+speaker+voice-fingerprint (paths+mtimes+settings) — cache under the engine that ACTUALLY synthesized, hit only on the intended engine.
- Quarantine timing-rejected synthesis and allow one fresh attempt using the same engine, voice, and text before failing. Cache that replacement only after it fits.
  **Why:** A cloned-voice model generated approximately eight seconds of requested dialogue followed by sixteen seconds of unrelated speech. Reusing its cached output made retries deterministically fail; increasing the speed limit would preserve the hallucinated words.
  **How to apply:** Do not assume every timing failure means bad source timestamps or verbose translation. Inspect generated speech, keep retries bounded, and do not silently change the voice or translation.
**Why:** all three long-form failure modes confirmed on production content Aug 2026; short content masks them.
