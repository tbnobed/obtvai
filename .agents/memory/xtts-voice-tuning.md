---
name: XTTS voice tuning
description: What actually changes XTTS-v2 cloned voice output; preset/settings precedence convention
---

- XTTS sampling presets (temperature/top_p/top_k tweaks) sound nearly identical to users — speed and temperature are the only audible levers. Expose direct sliders instead of adding more presets.
- **Why:** user A/B-tested four presets and reported they only differed in pacing.
- Coqui `tts_to_file` forwards speed/temperature/top_p/top_k/repetition_penalty kwargs to XTTS inference; repetition_penalty must be a float.
- Convention: synthesis-style precedence is per-generation settings > per-generation preset (tuning runs) > person's saved custom settings > person's saved preset; choosing a preset clears saved custom settings.
- **How to apply:** keep this precedence for any new synthesis path (speak, tune, dub) and validate slider ranges server-side (mock server mirrors the same ranges).
- Cloned-voice dubbing prefers Chatterbox multilingual; `chatterbox-tts` pins old torch/transformers so it must be installed `--no-deps` (like facenet-pytorch) with its light deps added manually, or it silently downgrades the +cu128 torch pin.
- Chatterbox has no top_p/repetition_penalty equivalent — map temperature directly and speed via ffmpeg atempo; always keep XTTS as load-time and per-segment fallback since Chatterbox can't be tested off-GPU.
