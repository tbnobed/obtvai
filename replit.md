# obtv-ai

A fully local AI-powered media intelligence and semantic video search platform. Users place video files into a watched media folder; the system automatically discovers, processes, transcribes, indexes, and makes the content searchable from a browser — with timecode-precise playback, speaker diarization, face clustering, scene detection, and a local AI Q&A agent.

## Run & Operate

- `pnpm --filter @workspace/api-server run dev` — run the Node.js mock API server (Replit preview)
- `pnpm --filter @workspace/frontend run dev` — run the React frontend (Replit preview)
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec

## Stack

- pnpm workspaces, Node.js 24, TypeScript 5.9
- **Frontend:** React + Vite + Tailwind CSS (dark-mode, broadcast-grade UI)
- **Production backend:** FastAPI (Python) + Celery workers
- **Databases:** PostgreSQL + Drizzle ORM (Node.js), SQLAlchemy (Python)
- **Vector search:** Qdrant
- **Queue:** Redis + Celery
- **AI:** faster-whisper (transcription), pyannote.audio community-1 (diarization), SigLIP-2 (visual embeddings), InsightFace ArcFace (face clustering), BAAI/bge-m3 (text embeddings), Qwen3-8B (Q&A), MADLAD-400 (translation)
- **Media processing:** FFmpeg, ffprobe, PySceneDetect
- **Deployment:** Docker Compose (NVIDIA GPU support)
- **API codegen:** Orval (from OpenAPI spec)

## Where things live

- `lib/api-spec/openapi.yaml` — Single source of truth for all API contracts
- `lib/api-client-react/src/generated/` — Generated React Query hooks
- `artifacts/frontend/src/` — React frontend (pages, components)
- `artifacts/api-server/src/routes/mock.ts` — Mock API data for Replit preview
- `services/api/` — FastAPI backend (production)
- `services/worker/tasks/` — Celery processing tasks (transcribe, diarize, scene detect, embed, etc.)
- `services/watcher/` — File system watcher for auto-ingest
- `docker-compose.yml` — Full production deployment stack
- `.env.example` — Environment variable reference

## Architecture decisions

- OpenAPI-first contract: spec gates both the React Query client and the Zod validators on the server
- Replit hosts the UI/development environment; production runs entirely via Docker Compose on a local GPU server
- The Node.js API server in Replit serves mock data so the UI can be previewed without GPU hardware
- Source media is mounted read-only; no source files are ever modified or deleted
- All AI inference is local — no cloud APIs, no data leaves the network after initial model downloads
- Processing jobs are tracked individually with status/progress/logs/retry support

## Product

- **Media library:** Browse all indexed video assets with status, duration, codec info; upload video files directly from the browser (`POST /media/upload`, stored under `UPLOAD_PATH` → `/uploads`) in addition to watched-folder ingest
- **Asset detail:** Video player with timecode deep-linking, scene timeline, full transcript with speaker labels, face clusters, processing job history
- **Semantic search:** Natural language search across transcripts and visual scene content; results link directly to the matching timecode in the video player
- **Processing pipeline:** Real-time job monitoring with progress bars, logs, retry/cancel
- **AI Q&A:** Ask questions about the video library; answers cite source files and timecodes
- **External trends:** Insights page "Trending Now" — per-topic YouTube search (most-viewed past-week videos for top library topics) + self-hosted SearXNG news momentum per topic; auto-refreshes every 3 h, manual refresh queues a `trends` job (`POST /trends/refresh`)
- **Projects:** Optional `target_runtime_seconds` per project (set in New Project dialog or the detail-page header). Rule: everything created inside the project inherits it as the default duration — story builder and reels fall back to the project target when no explicit duration is given (enforced server-side in `routers/stories.py`/`reels.py` and mirrored in mock.ts); an explicit per-job duration always wins
- **Clip lists:** Build named clip lists from search results, export as EDL/CSV/JSON
- **Ratings:** Provider-agnostic audience measurement (`/ratings`) — CSV import (Nielsen/Comscore/iSpot/manual, lenient header aliases, demo_* columns → JSONB), own-station KPIs + daily trend, competitive station share ranking, top programs, per-record linking to library assets (asset detail grows a Ratings tab when linked); own vs competitive is computed at read time from `OWN_STATIONS`
- **Socials:** `/socials` page — programs (e.g. "Praise") group social channels (YouTube/Instagram/Facebook/TikTok, owned or public); channel-level follower growth (snapshots, 90d area chart, week-over-week delta) + per-post metrics; synced every 6 h by worker `social_sync` task or via Refresh (`POST /socials/refresh`, singleton job); YouTube uses `YOUTUBE_API_KEY`, IG/FB use `META_ACCESS_TOKEN` (+`META_IG_USER_ID` for IG business_discovery), TikTok stubbed until `TIKTOK_ACCESS_TOKEN` wiring; per-channel errors land in `last_error`, never fail the whole run; "AI Insights" button (`POST /socials/insights`, viewer-allowed) runs the local Q&A LLM over current metrics (heuristic fallback when the model is unavailable)
- **User accounts:** Fully local login (username/password, HttpOnly session cookie, bcrypt). Roles: `admin` (user management + everything), `user` (everything except user management), `viewer` (read-only + search/AI Q&A). Admin page at `/users`; first admin bootstrapped from `ADMIN_USERNAME`/`ADMIN_PASSWORD` (random password printed once in api log if unset)

## User preferences

- EVERY reply that changes code must END with the exact production deploy command, listing only the services that changed (e.g. `git pull && docker compose up -d --build frontend`), plus a clear summary of what changed. No exceptions — including short replies and follow-up fixes.
- There is NO compose service named `worker` — worker code changes deploy as `worker-gpu worker-gpu-2 worker-cpu worker-graphics` (all build from the same `services/worker` image).
- The deploy command must be in the FINAL user-facing chat message of the turn — never only in intermediate progress notes, and never omitted because a task tracker or checkpoint "closed" the work.
- If a change requires ANY server action beyond `git pull && docker compose up -d --build ...` (new `.env` variables, one-time commands, config edits, credentials), state those steps explicitly in the chat next to the deploy command — documenting them only in `.env.example` or elsewhere in the repo is not enough.

## Gotchas

- Always restart the API server workflow after changing `src/routes/mock.ts`
- Auth is enforced by ASGI middleware on all `/api/*` paths (incl. the StaticFiles thumbnail mount) — allowlist only `/api/auth/login` + `/api/healthz`; viewer POST allowlist lives in `services/api/app/auth.py` (`VIEWER_POST_ALLOWLIST`) and must be mirrored in `artifacts/api-server/src/routes/auth.ts`
- `INTERNAL_API_TOKEN` env is REQUIRED in production — the watcher authenticates with the `X-Internal-Token` header; watched-folder ingest breaks without it
- Mock preview logins: `admin` / `editor` / `viewer`, all password `obtv` (in-memory, reset on workflow restart)
- Use the `bcrypt` package directly, never passlib (passlib 1.7.4 breaks with bcrypt>=4.1 and was removed from requirements)
- Re-run codegen after any OpenAPI spec change: `pnpm --filter @workspace/api-spec run codegen`
- The production stack requires a HuggingFace token for pyannote speaker diarization — see `.env.example`
- Docker Compose GPU workers require NVIDIA Container Toolkit on the host
- Voice cloning uses XTTS-v2 (coqui-tts); first run downloads ~2 GB model; `COQUI_TOS_AGREED=1` is set in docker-compose shared env; voice files live under `/artifacts/voices`
- Dub lip sync (per-dub "Lip sync" checkbox → `DubRequest.lip_sync`) is a vendored Wav2Lip-GAN pass in `services/worker/tasks/lipsync.py` — MuseTalk/LatentSync were rejected (dependency stacks conflict with the torch 2.8/cu128 pin); weights download from HF on first use (~400 MB, override via `LIPSYNC_MODEL_REPO`/`LIPSYNC_MODEL_FILE` or local `LIPSYNC_MODEL_PATH`); only frames inside dubbed speech spans with a confident face are touched; the mel input must be the speech-only mix (pre-background), and failure falls back to the audio-only dub
- Dubs keep the original background audio via Demucs vocal separation (bundled in torchaudio's `HDEMUCS_HIGH_MUSDB_PLUS` pipeline — no extra pip deps; first run downloads ~300 MB); disable with `DUB_KEEP_BACKGROUND=0`, level via `DUB_BG_GAIN` (default 0.9); failure falls back to speech-only dub
- Cloned-voice dubbing AND the Voice Generator (person page) prefer Chatterbox multilingual (`chatterbox-tts`, installed `--no-deps` to protect the torch pin); first run downloads ~3 GB; falls back to XTTS-v2 per-load and per-segment; force old engine with `DUB_ENGINE=xtts`
- `BASE_PATH` env var must be set when running `pnpm build` manually (handled automatically by workflows)
- After changing `EMBEDDINGS_MODEL` or `VISION_MODEL`, the search index must be rebuilt (Jobs page → "Rebuild Search Index" → `POST /search/reindex`); Qdrant collections auto-recreate on dim mismatch
- FaceNet/pyannote-3.1-era embeddings don't match the new ArcFace/community-1 stack — run People → "Re-analyze Library" after upgrading
- Picture lock: `ClipList.locked` — API returns 423 on clip/delete mutations while locked; toggle `locked` via PATCH first (the lock field itself is always writable)
- QC flags run automatically at ingest (worker `qc` task, CPU queue: volumedetect + blackdetect → `media_assets.qc_flags` JSONB)
- Second media source: `MEDIA_PATH_2` mounts at `/media2` inside containers (NOT nested under the read-only `/media` — Docker cannot create a mountpoint inside a ro mount); watcher uses PollingObserver (inotify doesn't fire on SMB/NFS) + startup scan; `POST /media` dedupes by `original_path`
- Graphics generator drives the host's existing ComfyUI over HTTP (`COMFYUI_URL`, default `http://host.docker.internal:8188` via `extra_hosts: host-gateway`); ComfyUI must be started with `--listen` (and its port open to the docker bridge) or every preset shows "ComfyUI unreachable"
- Two ComfyUI instances (user runs one for image, one for video): set `COMFYUI_URL_IMAGE` / `COMFYUI_URL_VIDEO` — presets, generation, and cancel route by preset kind; unset kinds fall back to `COMFYUI_URL`; availability is gated per instance
- Graphics presets are availability-gated against ComfyUI `/object_info` (node classes + model filenames, cached 30 s); custom presets = API-format workflow JSONs dropped into `COMFY_WORKFLOWS_PATH` (default `./comfy_workflows`, see its README) — prompt injects into the `CLIPTextEncode` node titled "prompt"
- Model filenames in presets fuzzy-resolve to the files each ComfyUI actually has (`resolve_model_files` in `comfy_graphics.py`): token-boundary matching, precision/quant suffixes ignored, version digits kept (wan2.1 never matches wan2.2, t5xxl never matches umt5); worker re-resolves against fresh `/object_info` before every submit
- `comfy_graphics.py` is intentionally duplicated in `services/api/app/` and `services/worker/` (separate Docker build contexts) — keep both copies identical
- Graphics video presets end in `SaveImage` (PNG sequence); the graphics worker assembles the MP4 with ffmpeg at the preset fps — no dependency on ComfyUI video-save nodes; worker-graphics has NO GPU reservation (ComfyUI owns the GPUs)
- Trends: SearXNG JSON output must stay enabled in `searxng/settings.yml` (`search.formats` includes `json` — it's OFF in SearXNG defaults, worker gets 403 without it); only topic keywords go out; YouTube side is per-topic `search.list` (NOT the global trending chart — zero overlap with a specialised library) at 100 quota units/call: 10 topics × 8 runs/day ≈ 8k of the 10k default daily quota, tune via `YT_TOPIC_LIMIT` in `tasks/trends.py`; trend↔library matching happens at read time in `GET /trends`, stored rows only hold the fetched external data
- Ratings are provider-agnostic by design: `ratings_records.provider` + `import_id` are the seam for a future measurement-API ingest (a worker task would create an import batch + insert rows — no schema change); `is_own` is NEVER stored, it's computed at read time from `OWN_STATIONS` (comma-separated env, e.g. `OBTV,OBTV2`) so callsign changes need no data migration; deleting an import batch cascades to its records; the CSV header-alias table exists twice — `services/api/app/routers/ratings.py` and `artifacts/api-server/src/routes/mock.ts` — keep in sync
- Curator-DIRECT ingest: `/curator` is a watched root (watcher `MEDIA_ROOTS` includes it) — watcher ingests only the `*_video.mp4` per proxy folder (`_should_ingest`); the proxy task self-links when the source IS a `_video.mp4`; hi-res original path is parsed from the sidecar metadata XML (schema-agnostic scan in `curator.find_sidecar_source_path`) into `media_assets.source_path`, which NLE exports prefer over `original_path`; Curator sidecars carry NO hi-res path in practice — fallback reconstructs `<CURATOR_SOURCE_ROOT><folder stem minus -HHMMSS><CURATOR_SOURCE_EXT>` (default `.mxf`); `/curator` must be mounted in api, watcher, and ALL media workers (gpu, gpu-2, cpu)
- IPV Curator proxy reuse: set `CURATOR_PROXY_PATH` to the WebProxy tree root — ingest matches by proxy FOLDER name (source basename + `-HHMMSS` timestamp, punctuation-normalized); the proxy is REMUXED (stream-copy, never symlinked) into a local `PROXIES_DIR/{media_id}.mp4` — Curator WebProxies are video-only fragmented MP4s with separate `_audioN.mp4` sidecars, and streaming via symlink off the SMB share stalls playback (endless tiny 206s); sidecar audio is muxed in (AAC), audio extraction also reads the sidecars; only H.264 proxies are reused (ffprobe-gated), others re-encode locally; folder index cached `CURATOR_INDEX_TTL` (900 s) in /artifacts; Curator's `<id>_subtitle.vtt` (its own STT) is used ONLY as a transcription fallback when Whisper fails (`_thumbnail.vtt` is a sprite index, ignored)
- NLE relink exports: `EXPORT_PATH_MAP` (semicolon `serverPath=editorPath` pairs, longest prefix wins, backslash targets auto-convert) rewrites original paths in EDL (`* SOURCE FILE:`), FCPXML (`media-rep src`), and OTIO (`target_url`) so Premiere/Resolve relink to hi-res
- Topic normalization is intentionally triplicated: `artifacts/api-server/src/lib/topics.ts`, `services/api/app/topic_norm.py`, `services/worker/topic_norm.py` — keep all three in sync (the two Python copies must be byte-identical); topic filter URLs use the normalized key (`/library?topic=<key>&topic_label=<label>`); coverage-gap asset counts are computed at read time in the insights endpoint, not stored

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
- See `README.md` for full production deployment instructions
