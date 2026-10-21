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
