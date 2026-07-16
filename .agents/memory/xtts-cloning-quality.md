---
name: XTTS cloning quality
description: What actually helps vs hurts XTTS-v2 voice-clone naturalness
---

- Hand-tuned sampling overrides (temperature 0.65, repetition_penalty 9, top_p 0.8) made cloned speech WORSE (flatter/more robotic) than XTTS-v2 stock inference defaults — keep defaults.
- Conditioning on many mixed reference wavs blurs the voice; 1-2 longest clean samples beat 6.
- **How to apply:** biggest quality lever is sample recording quality, not inference knobs.
