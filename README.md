# obtv-ai

A fully local AI-powered media intelligence and semantic video search platform.

Runs entirely on-premises — no cloud APIs, no data leaves your network.

---

## Requirements

- Ubuntu 22.04+ server
- NVIDIA GPU with CUDA support (RTX 3090 or better recommended; RTX PRO 6000 Blackwell for production)
- NVIDIA driver 570+ (containers use CUDA 12.8 + PyTorch cu128 wheels — required for Blackwell GPUs)
- NVIDIA Container Toolkit
- Docker Engine 24+
- Docker Compose v2.x
- Local media storage (SMB, NFS, or directly mounted)

On multi-GPU or shared machines, set `GPU_DEVICE_ID` in `.env` to pin the whole stack
to one GPU (default: `1`). All AI services (API + GPU worker) respect this setting.

---

## Quick Start

### 1. Clone and configure

```bash
git clone <repo> obtv-ai
cd obtv-ai
cp .env.example .env
# Edit .env — set MEDIA_PATH and HF_TOKEN
```

### 2. First-time model download

On the GPU server, pre-pull the AI models before starting (optional but prevents cold-start delays):

```bash
docker compose run --rm worker-gpu python -c "
from faster_whisper import WhisperModel; WhisperModel('large-v3', device='cpu', compute_type='int8')
from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
from transformers import CLIPModel; CLIPModel.from_pretrained('openai/clip-vit-base-patch32')
"
```

### 3. Start

```bash
docker compose up -d
```

The app is available at **http://localhost:3000**

Celery Flower monitoring: **http://localhost:5555**

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Browser  →  nginx :80  →  React SPA                           │
│                       →  FastAPI /api  →  PostgreSQL            │
│                                        →  Qdrant (vectors)      │
│                                        →  Redis (job queue)     │
│                                                                  │
│  worker-gpu (CUDA)  ←  Redis  ←  API triggers                  │
│    • Whisper transcription                                       │
│    • Speaker diarization (pyannote)                              │
│    • CLIP visual embeddings                                      │
│    • FaceNet face detection + clustering                         │
│                                                                  │
│  worker-cpu  ←  Redis                                           │
│    • ffmpeg proxy creation                                       │
│    • Scene detection (PySceneDetect)                             │
│    • Transcript indexing into Qdrant                             │
│                                                                  │
│  watcher  →  watches MEDIA_PATH  →  auto-triggers ingest        │
└─────────────────────────────────────────────────────────────────┘
```

## Processing Pipeline

When a video is discovered (via the UI or file watcher):

1. **Ingest** — ffprobe extracts technical metadata
2. **Proxy** — ffmpeg creates H.264/AAC browser-compatible MP4 + thumbnail
3. **Audio extract** — ffmpeg extracts 16kHz mono WAV
4. **Transcription** — faster-whisper with GPU acceleration
5. **Diarization** — pyannote.audio assigns speaker labels to segments
6. **Scene detection** — PySceneDetect identifies scene boundaries
7. **Visual embeddings** — CLIP encodes scene thumbnails → Qdrant
8. **Face detection** — MTCNN detects faces; FaceNet clusters them
9. **Indexing** — sentence-transformers embeds transcript → Qdrant

## Semantic Search

Search uses dense vector retrieval against:
- **Transcript embeddings** (all-MiniLM-L6-v2) for speech content
- **Visual embeddings** (CLIP) for scene content

Both use Qdrant cosine similarity. Results resolve to `(asset_id, start_time, end_time)` and link directly to the video player at the matching timecode.

## AI Q&A

The AI Q&A page retrieves the most relevant transcript segments via Qdrant, then feeds them as context to a local instruction-tuned LLM (default: Llama 3.2 3B Instruct). Every answer cites the source asset and timecode.

To change the model, set `LLM_MODEL` in `.env`:
```bash
LLM_MODEL=meta-llama/Llama-3.2-1B-Instruct   # faster, less VRAM
LLM_MODEL=mistralai/Mistral-7B-Instruct-v0.3 # smarter, ~16 GB VRAM
```

Note: Llama models are gated on HuggingFace — accept the license on the model page and set `HF_TOKEN` in `.env`.

## Data Storage

| Data | Location |
|------|----------|
| Source media | `$MEDIA_PATH` (read-only mount) |
| Browser proxies | `artifacts_data` volume (`/artifacts/proxies`) |
| Thumbnails | `artifacts_data` volume (`/artifacts/thumbnails`) |
| Extracted audio | `artifacts_data` volume (`/artifacts/audio`) |
| Metadata DB | `postgres_data` volume |
| Vector index | `qdrant_data` volume |
| Job queue | `redis_data` volume |

Source media is **never modified or deleted**.

## Configuration

See `.env.example` for all environment variables.

| Variable | Default | Description |
|----------|---------|-------------|
| `MEDIA_PATH` | `./sample_media` | Path to your video library |
| `GPU_DEVICE_ID` | `1` | Which GPU (nvidia-smi index) the stack uses |
| `WHISPER_MODEL` | `large-v3` | Whisper model size |
| `LLM_MODEL` | `Llama-3.2-3B-Instruct` | Local LLM for AI Q&A |
| `HF_TOKEN` | — | HuggingFace token for diarization + gated Llama models |
| `EMBEDDINGS_MODEL` | `all-MiniLM-L6-v2` | Text embedding model |
| `VISION_MODEL` | `clip-vit-base-patch32` | Visual embedding model |
