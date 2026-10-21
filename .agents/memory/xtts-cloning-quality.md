---
name: XTTS cloning quality
description: What actually helps vs hurts XTTS-v2 voice-clone naturalness
---

- Hand-tuned sampling overrides (temperature 0.65, repetition_penalty 9, top_p 0.8) made cloned speech WORSE (flatter/more robotic) than XTTS-v2 stock inference defaults — keep defaults.
- Conditioning on many mixed reference wavs blurs the voice; 1-2 longest clean samples beat 6.
- **How to apply:** biggest quality lever is sample recording quality, not inference knobs.

- The user approved the Spanish opening audition as maintaining the same voice throughout without the hallway echo. It used the actual presenter's source voice, vocal isolation to reduce background music, one fixed reference and Spanish Chatterbox engine, and no speed-up.
  **Why:** The previous mixed stock/cloned dub had audible accent and room-sound variation; this approach received explicit listening approval.
  **How to apply:** Preserve the approved reference and synthesis approach for this presenter's full dub. Validate other speakers separately; do not assume their references or the full program have also been approved.

- A fixed voice reference and engine do not by themselves guarantee consistent cross-language accent.
  **Why:** The user heard an American accent at the start of another speaker's Spanish dialogue despite fixed conditioning, disappearing after several sentences. Chatterbox documents reference-language accent transfer: https://github.com/resemble-ai/chatterbox
  **How to apply:** Audition the introduction together with subsequent dialogue. Test reference-language matching separately from engine consistency. The documented zero-guidance mitigation degraded recognition in a regional V3 trial; do not assume it is an improvement or deploy it globally. Any synthetic Spanish conditioning reference must be disclosed and checked for voice-identity drift.
