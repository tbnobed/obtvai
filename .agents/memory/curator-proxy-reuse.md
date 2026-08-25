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

## Selective ingest (Aug 2026)
- /curator is always watched; watcher polls `/api/curator/selected` (internal token) every ~45s and only ingests *_video.mp4 under admin-selected folders. `CURATOR_DIRECT_INGEST=1` = ingest everything (legacy).
- Layout heuristic everywhere (sidebar scanner + folder mirroring): a dir with exactly ONE *_video.mp4 is a clip folder (counts toward parent, not browsable); multiple = flat content folder (browsable, keeps its mirrored library folder).
- Re-check selection at ingest time, not just enqueue time (deselect race); mirror get-or-create chain runs under pg_advisory_xact_lock('obtv_curator_mirror').

## Gateway API query quirks
- The TBN Curator client-credentials token request must omit `scope` unless the OAuth client explicitly requires it.
  - **Why:** this Gateway returned HTTP 500 when `scope` was included even though the OpenAPI document advertises scopes.
  - **How to apply:** match the working Postman form exactly: client ID, client secret, and `grant_type=client_credentials`.
- Asset search returns HTTP 500 when `names` contains unknown metadata fields.
  - **Why:** broad guessed field lists made every otherwise-valid Media ID query fail; a minimal query succeeded immediately.
  - **How to apply:** first query without `names`, inspect returned field names, then request only verified names. Treat a 500 as a possible bad metadata name before blaming credentials.

## ClipLink OBTV extension automation
- The OBTV extension is not equivalent to Gateway `/api/v1/assets/sendto`. It submits `Plug-in - Send to genericV4` through ClipLink `PluginHandler/SubmitProcess`, with `AssetIds` and destination `MODIFY-ASSET-CURATORFOLDERPATH,EXPORT-OBTV-XML`, then polls `PluginHandler/GetProcess`.
  - **Why:** Gateway SendTo returned a completed no-op, while a ten-asset sequential production gate through the same-origin ClipLink process completed cleanly.
  - **How to apply:** for one-time bulk operation, run a reviewed same-origin browser script in an authenticated ClipLink session; never copy/store browser cookies. Treat status 32 as queued, 2 as running, and 4 with progress 1 as complete, then verify XML and OBTV before expanding beyond the gate. Persist each returned process ID and resume polling it after network interruption instead of submitting the asset again.
