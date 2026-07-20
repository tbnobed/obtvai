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
- **External trends:** Insights page "Trending Now" — YouTube trending chart matched against library topics + self-hosted SearXNG news momentum per topic; auto-refreshes every 3 h, manual refresh queues a `trends` job (`POST /trends/refresh`)
- **Clip lists:** Build named clip lists from search results, export as EDL/CSV/JSON

## User preferences

- EVERY reply that changes code must END with the exact production deploy command, listing only the services that changed (e.g. `git pull && docker compose up -d --build frontend`), plus a clear summary of what changed. No exceptions — including short replies and follow-up fixes.
- There is NO compose service named `worker` — worker code changes deploy as `worker-gpu worker-gpu-2 worker-cpu worker-graphics` (all build from the same `services/worker` image).

## Gotchas

- Always restart the API server workflow after changing `src/routes/mock.ts`
- Re-run codegen after any OpenAPI spec change: `pnpm --filter @workspace/api-spec run codegen`
- The production stack requires a HuggingFace token for pyannote speaker diarization — see `.env.example`
- Docker Compose GPU workers require NVIDIA Container Toolkit on the host
- Voice cloning uses XTTS-v2 (coqui-tts); first run downloads ~2 GB model; `COQUI_TOS_AGREED=1` is set in docker-compose shared env; voice files live under `/artifacts/voices`
- Cloned-voice dubbing prefers Chatterbox multilingual (`chatterbox-tts`, installed `--no-deps` to protect the torch pin); first run downloads ~3 GB; falls back to XTTS-v2 per-load and per-segment; force old engine with `DUB_ENGINE=xtts`
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
- Trends: SearXNG JSON output must stay enabled in `searxng/settings.yml` (`search.formats` includes `json` — it's OFF in SearXNG defaults, worker gets 403 without it); only topic keywords go out; YouTube trending uses `YOUTUBE_API_KEY` (or the OAuth trio) with `TRENDS_REGION`; trend↔library matching happens at read time in `GET /trends`, stored rows only hold the fetched external data
- Topic normalization is intentionally triplicated: `artifacts/api-server/src/lib/topics.ts`, `services/api/app/topic_norm.py`, `services/worker/topic_norm.py` — keep all three in sync (the two Python copies must be byte-identical); topic filter URLs use the normalized key (`/library?topic=<key>&topic_label=<label>`); coverage-gap asset counts are computed at read time in the insights endpoint, not stored

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
- See `README.md` for full production deployment instructions
