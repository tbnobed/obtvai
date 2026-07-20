---
name: MMS-TTS coverage & usage
description: Which languages facebook/mms-tts supports and the uroman/prefork gotchas when using it in Celery workers.
---

# MMS-TTS (facebook/mms-tts-{iso639-3})

- **No model exists for Italian (ita), Japanese (jpn), or Chinese (cmn/zho).** Verified via HF API. Of the app's 12 translation languages, only es/fr/de/pt/nl/ru/ko/ar/hi can be dubbed.
- **Why:** MMS-TTS training data (religious recordings) never covered those languages; requesting them 401s on the hub.
- **How to apply:** any TTS feature must gate language lists separately from translation language lists; check `https://huggingface.co/api/models/facebook/mms-tts-<code>` before assuming coverage.
- Some checkpoints set `tokenizer.is_uroman=True` (non-Latin scripts) — input must be romanized first; the `uroman` PyPI package (Python port) handles it without the perl tool.
- Load via `snapshot_download` then `from_pretrained(local_dir)` — same daemonic-prefork-safe pattern as other HF loads in Celery workers.
- VITS output is mono at `model.config.sampling_rate` (typically 16 kHz); fit clips into transcript slots with ffmpeg `atempo` (pitch-preserving), not resampling.
- Chatterbox + transformers>=4.48: generation requests output_attentions, sdpa attention rejects it — after from_pretrained, set `_attn_implementation = "eager"` on every HF submodule config (t3/s3gen/ve and their .tfmr) or every generation dies with "output_attentions ... set it to 'eager'".
