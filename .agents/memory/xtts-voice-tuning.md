---
name: XTTS voice tuning
description: What actually changes XTTS-v2 cloned voice output; preset/settings precedence convention
---

- XTTS sampling presets (temperature/top_p/top_k tweaks) sound nearly identical to users — speed and temperature are the only audible levers. Expose direct sliders instead of adding more presets.
- **Why:** user A/B-tested four presets and reported they only differed in pacing.
- Coqui `tts_to_file` forwards speed/temperature/top_p/top_k/repetition_penalty kwargs to XTTS inference; repetition_penalty must be a float.
- Convention: synthesis-style precedence is per-generation settings > per-generation preset (tuning runs) > person's saved custom settings > person's saved preset; choosing a preset clears saved custom settings.
- **How to apply:** keep this precedence for any new synthesis path (speak, tune, dub) and validate slider ranges server-side (mock server mirrors the same ranges).
