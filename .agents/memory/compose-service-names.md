---
name: Deploy command service names
description: Exact docker compose service names on obtv-llm-2 — there is NO service named "worker"
---
Compose services: postgres, redis, searxng, qdrant, flower, api, worker-gpu, worker-gpu-2, worker-cpu, worker-graphics, watcher, frontend.

**Rule:** the deploy command at the end of every code-changing reply must list only these exact names. A change under `services/worker/` rebuilds ALL worker images: `worker-gpu worker-gpu-2 worker-cpu worker-graphics`. `services/api/` → `api`. Frontend → `frontend`. Panel-only → bare `git pull`.

**Why:** told the user `--build worker` — "no such service: worker" — after they explicitly demanded the command be right every time.

Compose container labels preserve the configuration-file list but not transient shell variables used at launch. Reconstruct required image variables from the running service before reusing an override stack.

**Why:** The frontend's playback override required an image variable absent from a fresh SSH shell, stopping an otherwise valid frontend build. Substituting the newly built API image would also risk unintentionally changing the pinned playback version.

**How to apply:** Supply `PLAYBACK_API_IMAGE` from the running playback container's configured image to the deployment subprocess only. Keep `--no-deps --no-build` on targeted service activation so unrelated playback and worker services are not recreated.
