---
name: Driving ComfyUI over REST
description: Reliable patterns for submitting/polling/cancelling ComfyUI jobs from external services
---

- `/history/{prompt_id}` only contains an entry once execution FINISHED — "entry exists" is the done signal; check `status.status_str == "error"` and `status.completed` before collecting outputs.
- `/queue` items are arrays: `item[1]` is the prompt_id (both `queue_running` and `queue_pending`). Cancel = POST `/queue {"delete":[id]}` for queued + POST `/interrupt` only if it's the currently running item.
- No per-node progress over plain REST (websocket only) — use time-based progress creep with a per-kind estimate.
- **End video workflows in `SaveImage`** (PNG sequence) and assemble mp4 with ffmpeg at the model's fps — avoids depending on any video-save custom node (VHS etc.).
- Gate preset availability against `/object_info`: node class must exist AND model filenames must appear in the loader input's options list (match by basename — Comfy lists subfolder paths). Cache it (~30 s); the payload is huge.
- From Docker: `host.docker.internal` + `extra_hosts: host-gateway`; ComfyUI must run `--listen` or containers can't reach it.
- Cancel race: worker status UPDATEs must carry `AND status != 'cancelled'` or the API's cancel gets overwritten in the window before comfy_prompt_id is stored.
- Poll loops for long renders must tolerate consecutive transient HTTP failures (~8 polls) before erroring — one blip during a 10-min render otherwise kills a job ComfyUI keeps rendering.
- Installs name the same model differently (fp8 vs fp16, Q8 vs Q5, HighNoise vs high_noise) — fuzzy-resolve preset filenames against the loader's options list before submitting. Match at token boundaries only (raw substring lets t5xxl hit inside umt5_xxl) and merge version digits into the family token (else wan2.1 VAE silently matches wan2.2 VAE — not interchangeable).

**Why:** learned building the graphics generator; each item was either a race or a silent-failure mode found in review.
**How to apply:** any feature submitting workflows to ComfyUI or similar queue-based render services over HTTP.
