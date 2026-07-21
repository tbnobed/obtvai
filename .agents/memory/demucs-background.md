---
name: Demucs background separation in dubs
description: Vocal/background separation without new pip deps; streaming chunk rules for long assets
---
- torchaudio (pinned 2.8.0+cu128) bundles Demucs via `torchaudio.pipelines.HDEMUCS_HIGH_MUSDB_PLUS` — use it instead of the `demucs` pip package (which drags dora-search etc. and risks the torch pin). Background = sum(sources) − vocals.
- **Why:** installing demucs normally churns the pinned torch stack; the bundled pipeline has zero extra deps.
- Gotcha: the source list (`drums, bass, other, vocals`) is an attribute of the model, not the bundle — `bundle.sources` raises AttributeError; use `model.sources`.
- **How to apply:** for hour-plus assets never materialize full-length 44.1k stereo tensors — stream with `torchaudio.load(frame_offset, num_frames)`, do a chunked stats pass for global mean/std (per-chunk stats pump levels), 20 s chunks with 1 s complementary linear crossfades (sum to 1, so no weight buffer), accumulate into one mono buffer at the target rate.
