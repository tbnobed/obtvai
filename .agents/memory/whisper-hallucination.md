---
name: Whisper silence hallucination
description: faster-whisper hallucinates cues on silent/ambient audio unless VAD filtering is enabled
---

Faster-whisper without `vad_filter=True` hallucinates short cues ("You", "Thank you.") on silence — recognizable by cues landing at exact 30 s window boundaries (:00/:30 timestamps). Common on dailies/ambient-only material.

**Why:** Whisper decodes every 30 s window even with no speech; the decoder emits its most probable filler tokens, and `condition_on_previous_text` (default True) seeds repetition loops from one hallucinated window to the next.

Related: camera/dailies .mov files carry multiple mono audio tracks; ffmpeg default stream selection grabs only ONE (often silent) — audio extraction for transcription must amix ALL audio streams of the source, or Whisper sees silence.

**How to apply:** any `model.transcribe(...)` call must pass `vad_filter=True` (plus `vad_parameters={"min_silence_duration_ms": 500}`) and `condition_on_previous_text=False`. Transcription is always local GPU — the remote LLM offload (Spark) never touches Whisper.

## Phase-cancelled stereo dailies
Some camera .movs record the same mic on L and R with inverted polarity: each channel is loud (~-30 dB) but the forced mono downmix (`-ac 1`) sums to near-silence (~-91 dB), so Whisper sees a silent WAV → 0 segments. Detection: measure the extracted WAV's max_volume; if < -45 dB, probe every input/stream/channel with `pan=mono|c0=cN` and re-extract the loudest single channel. Note: volumedetect on a stereo file measures channels individually, NOT the mono sum — a "loud" stereo source can still cancel to silence.
