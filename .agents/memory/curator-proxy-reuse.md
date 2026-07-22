---
name: Curator proxy reuse & media serving off network mounts
description: IPV Curator WebProxy layout (video-only fMP4 + audio sidecars) and why proxies must be local files, never symlinks into SMB.
---

- IPV Curator WebProxy folders hold SEPARATE files: `<id>_video.mp4` (video-only, fragmented MP4, H.264) + `<id>_audio0.mp4` [, `_audio1`…] sidecars. The video file alone has NO audio stream — audio extraction and playback must pull in the sidecars.
  - **Why:** audio_extract failed with ffmpeg "Output file does not contain any stream", and symlinked proxies played silent.
  - **How to apply:** any task consuming a Curator `_video.mp4` must check `has_audio_stream()` and fall back to `find_curator_audio()` sidecars (amix when multiple).
- Never serve browser media via symlink into a network (SMB) mount. Chrome shows an endless staircase of tiny ~30 kB 206 range requests and the player spins forever: each read stalls, the connection drops, Chrome resumes with the next range.
  - **Why:** the "video never loads" incident — proxy was a symlink into `/curator`.
  - **How to apply:** materialize a local file (stream-copy remux is enough — no re-encode). A `-c copy -movflags +faststart` remux also converts fragmented MP4 into progressive MP4, which browsers buffer properly.
- A/V from separate Curator render files muxes cleanly (`-map 0:v:0` + sidecar audio → AAC); both are rendered from the same source so timestamps align from 0.
