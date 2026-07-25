---
name: Whisper silence hallucination
description: faster-whisper hallucinates cues on silent/ambient audio unless VAD filtering is enabled
---

Faster-whisper without `vad_filter=True` hallucinates short cues ("You", "Thank you.") on silence — recognizable by cues landing at exact 30 s window boundaries (:00/:30 timestamps). Common on dailies/ambient-only material.

**Why:** Whisper decodes every 30 s window even with no speech; the decoder emits its most probable filler tokens, and `condition_on_previous_text` (default True) seeds repetition loops from one hallucinated window to the next.

**How to apply:** any `model.transcribe(...)` call must pass `vad_filter=True` (plus `vad_parameters={"min_silence_duration_ms": 500}`) and `condition_on_previous_text=False`. Transcription is always local GPU — the remote LLM offload (Spark) never touches Whisper.
