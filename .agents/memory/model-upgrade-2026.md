---
name: Model stack upgrade notes
description: Pitfalls from upgrading LLM/embedding/vision/diarization/face models; embedding-space compatibility rules
---

# Model upgrade lessons (July 2026 stack refresh)

Stack: Qwen3-8B (Q&A), BAAI/bge-m3 (text embeds), SigLIP-2 so400m (visual), MADLAD-400 (translate), pyannote community-1 (diarize), InsightFace buffalo_l (faces).

**Rules:**
- Embedding spaces are never cross-compatible: changing an embedding model requires re-embedding everything it indexed AND recreating Qdrant collections (dims differ: MiniLM 384 → bge-m3 1024; CLIP 768 → SigLIP 1152). `_ensure_collection` auto-recreates on dim mismatch in both workers and api startup.
- SigLIP has no `projection_dim`; embedding dim = `text_config.hidden_size` (1152 for so400m). Use `AutoModel`/`AutoProcessor` — works for both CLIP and SigLIP. SigLIP text queries need `padding="max_length", max_length=64` to match training.
- SigLIP cosine score band is much lower than CLIP's (~0.02–0.22 vs 0.15–0.35) — rescale floors/ceils must be model-family aware.
- pyannote 4.0: `use_auth_token` → `token`; pipeline output may be an object with `.speaker_diarization`/`.speaker_embeddings` instead of a tuple; `return_embeddings=True` may raise TypeError — handle both defensively.
- ArcFace (InsightFace) similarity scale ≠ FaceNet: same-person ~0.5–0.8. DBSCAN eps 0.30→0.45, identify face threshold 0.70→0.55. Mixing old and new face/voice embeddings gives wrong matches — full re-analyze required after switch.
- Qwen3: pass `enable_thinking=False` to `apply_chat_template` or answers contain reasoning traces.
- MADLAD-400 selects target language via text prefix `<2xx> ` (ISO-639-1), not forced BOS tokens like NLLB.
- insightface needs g++ in the image to build; runs on onnxruntime-gpu, not torch.

## MADLAD degeneration
MADLAD-400 beam search can degenerate into repetition loops ("......", "1.1.1.1.") on some segments. Fix: `no_repeat_ngram_size=4` in generate + a post-process that collapses dot runs / repeated short chunks and truncates outputs >4x source length. Regexes are intentionally broad — if legit repeated phrasing gets collapsed, tighten to numeric/punctuation patterns first.
