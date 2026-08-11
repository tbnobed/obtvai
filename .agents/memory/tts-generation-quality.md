---
name: Cloned-voice TTS generation pitfalls
description: Chatterbox/XTTS long-text truncation and input casing issues in the voice generator
---

- Chatterbox `model.generate()` caps at roughly 40s of audio per call and silently truncates longer text. Long scripts must be split into sentence-grouped chunks (~280 chars), synthesized per chunk, and concatenated (short ~0.25s gap between chunks reads naturally).
- ALL-CAPS input garbles TTS output — models are trained on normally-cased text; caps tokenize into rare tokens. Normalize before synthesis: mostly-caps pastes → sentence case; in mixed text lowercase only shouted words >4 letters so real acronyms (TBN, NASA, U.S.) still spell out.
- "Match total runtime" is a post-processing step: ffmpeg pitch-preserving `atempo` on the finished file, clamped 0.5–2.0x. Keep it out of synthesis-settings precedence (pop it from the settings dict) or a target-only request wipes the person's saved voice style.
