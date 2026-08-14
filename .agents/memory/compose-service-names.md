---
name: Deploy command service names
description: Exact docker compose service names on obtv-llm-2 — there is NO service named "worker"
---
Compose services: postgres, redis, searxng, qdrant, flower, api, worker-gpu, worker-gpu-2, worker-cpu, worker-graphics, watcher, frontend.

**Rule:** the deploy command at the end of every code-changing reply must list only these exact names. A change under `services/worker/` rebuilds ALL worker images: `worker-gpu worker-gpu-2 worker-cpu worker-graphics`. `services/api/` → `api`. Frontend → `frontend`. Panel-only → bare `git pull`.

**Why:** told the user `--build worker` — "no such service: worker" — after they explicitly demanded the command be right every time.
