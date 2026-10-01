# Dedicated playback and authorized 500-viewer capacity test

## Scope and isolation

`app.playback_main:app` reuses the existing session auth middleware/database,
but never imports the main app, mounts thumbnails, initializes models, performs
DDL, bootstraps users, or starts ingest. It registers only health plus:

- `/api/media/{id}/playback`
- `/api/media/{id}/hls.m3u8`
- `/api/media/{id}/segments/{number}.ts`

Each media lookup selects four scalar columns into an immutable snapshot.
Its database session closes **before** mount access, ffprobe, ffmpeg, or response
delivery. Auth middleware also closes its own DB session before dispatch.
Nonarchive playback metadata still returns the main API's `/stream` URL.
Streams, downloads, images, thumbnails, dub/highlight streams, search, login,
media administration, workers and their topology remain unchanged.

The opt-in nginx replacement routes only those three **complete** playback
paths. Health remains on the main API through nginx. There is no playback
host port, GPU allocation, writable media mount, model-cache mount, artifacts
volume, nginx cache, nginx temp file, or persistent proxy in the new service.
The archive WebProxy tree is mounted read-only. `/tmp` is bounded tmpfs.
Existing bounded RAM caches live separately in each replica; restarts discard
them. Slow/disconnected clients retain only bounded delivery reservations.

## Opt-in preparation (operator only; not an automatic deployment)

Use the deployment's **existing compose project name and complete overlay
list**. Append `-f playback.compose.yml` **last**. Do not replace existing archive,
efficiency, remote-ingest, or storage overlays. Base compose is unchanged.

1. Confirm the approved server is unused for normal traffic. Confirm the actual
   SMB mount is healthy and `CURATOR_PROXY_PATH` points to that mounted WebProxy
   tree (not an empty local folder). Set `CURATOR_ARCHIVE_MODE=1` only if already
   approved for that deployment; the overlay does not silently enable it.
   Extra `CURATOR_ARCHIVE_ROOTS` need matching read-only playback mounts.
2. Confirm frontend's current nginx is **1.27.3 or newer**:
   `docker compose exec -T frontend nginx -v`. This config uses dynamically
   resolved upstream replicas (`resolve`, Docker DNS, shared upstream zone).
   Older nginx must be upgraded with an approved frontend image build first;
   never apply an incompatible config to a serving container.
3. Determine and export the existing API image tag without displaying secrets:

   ```sh
   export PLAYBACK_API_IMAGE="$(docker inspect --format '{{.Config.Image}}' "$(docker compose ps -q api)")"
   ```

   Build that same API image with the new entrypoint using
   `docker compose build api` (include existing compose options as usual).
   This **does not restart api**. Playback uses this image, not a second API
   image or a new dependency install. Verify any custom image-tag override
   points to the freshly built image.
4. Initially keep `PLAYBACK_REPLICAS=1`, `PLAYBACK_CPUS=4`,
   `PLAYBACK_ENCODE_JOBS=2`, `PLAYBACK_DELIVERIES=32`,
   `PLAYBACK_MEMORY_LIMIT=1g`. Validate the merged configuration locally with
   `docker compose -f docker-compose.yml -f playback.compose.yml config --quiet`
   (include all existing overlays). Do not print the full config; it can contain
   credentials.
5. Only after approval, opt in with:

   ```sh
   docker compose -f docker-compose.yml -f playback.compose.yml up -d --no-deps playback frontend
   ```

   This recreates only the new playback service and existing frontend/nginx,
   whose baked config is replaced by a read-only bind while the overlay is
   selected. No frontend build is required if its nginx already meets the version
   requirement. The bind must remain present and must not be edited in place on
   a serving host. Validate `nginx -t` after preparation, before opening traffic.

`PLAYBACK_REPLICAS` controls the number of CPU-only containers; there is no
`container_name` or host port to prevent scaling. DNS resolution automatically
tracks their addresses. Each replica runs exactly one uvicorn process, with a
separate bounded cache, semaphore and ordinary SQLAlchemy connection pool
(default up to 15 DB connections per process). Leave room in PostgreSQL's
connection budget for the main API/workers.

On the approved **32-CPU, 125-GiB host**, a candidate, **not a capacity claim**,
is four replicas, four CPUs, two simultaneous codec jobs and 1 GiB RAM each.
That caps playback at 16 CPUs/eight concurrent codec jobs, leaving headroom for
normal API work and the load generator. Do not jump to all 32 CPUs. Raise
delivery/cache/waiter bounds only after observing memory; a delivery may retain
12 MiB and encoding transient copies add more. Defaults are intentionally safe,
not a promise that 500 independent transcodes will succeed.

The overlay passes through bounded `PLAYBACK_*` metadata/segment cache,
single-flight and queue settings. They are per-replica. Default segment RAM is
64 MiB/64 entries, TTL 60s; metadata RAM is 512 KiB/256 entries, TTL 60s.
More replicas distribute CPU but do not share RAM caches; seeks to different
segments and independent clips cost substantially more than synchronized
same-clip viewers. Do not route overflow back to the model-bearing API.

Rollback: recreate only frontend using its **original** compose file list
without `playback.compose.yml`, then stop/remove the playback service using the
overlay. This removes the override mount and restores the baked nginx config.
Do not delete media, caches/proxies from the old deployment, or storage volumes.

## Harness: no k6 or package installation

`scripts/playback-load.py` uses Python stdlib plus **existing httpx** from the API
image. `--help`, input validation, offline plan and harness unit tests use only
stdlib. Nothing runs against a server without all of:

- `--execute`
- `--ack-target` matching the explicit HTTP(S) `--target` origin
- explicit `--max-users` (hard ceiling 500) and `--max-duration` (hard ceiling
  1800 seconds)
- `PLAYBACK_LOAD_TOKEN` in the environment, holding an authorized short-lived
  **application session**, not an internal/admin infrastructure token.

Target URLs cannot contain credentials, paths, queries or fragments. No tokens,
passwords, full exceptions, response bodies, asset IDs or search queries are
printed or written to reports. Do not enable shell tracing or HTTP debug logs.
Use a viewer session; main operator may create/revoke it internally. Virtual
viewers share this session: this tests authenticated traffic but **does not
claim 500 distinct account/session rows or login capacity**.

Prepare real approved media-ID files, outside version control:
`same.json` = a JSON array with exactly one HLS-playable media ID;
`distinct.json` = 500 different HLS-playable archive media IDs (or one ID per
line). Never duplicate IDs to pass the distinct scenario. It explicitly refuses
insufficient assets. A smaller `--stages 100`/`100,250` pilot needs 100/250 real
distinct IDs. Preflight negotiates real playback metadata and playlists, with
four concurrent requests, and refuses non-HLS assets.

Run an offline plan first:

```sh
python3 scripts/playback-load.py \
  --target "$APPROVED_TARGET" --scenario same --media-ids same.json \
  --search-query "$REAL_SEARCH_QUERY" --max-users 500 --max-duration 600
```

`APPROVED_TARGET` must be the actual authorized **nginx/frontend** origin, not
the direct playback port: normal browsing/search and exact routing must be
tested too. Then stage scripts/IDs in the already-running API container (the
API Dockerfile does not copy repository scripts):

```sh
docker cp scripts/playback-load.py "$(docker compose ps -q api)":/tmp/playback-load.py
docker cp same.json "$(docker compose ps -q api)":/tmp/playback-same.json
docker cp distinct.json "$(docker compose ps -q api)":/tmp/playback-distinct.json
```

With the secret already exported as `PLAYBACK_LOAD_TOKEN`, and a separately
running resource safety monitor, run **one scenario at a time**:

```sh
docker compose exec -T -e PLAYBACK_LOAD_TOKEN api python /tmp/playback-load.py \
  --target "$APPROVED_TARGET" --ack-target "$APPROVED_TARGET" --execute \
  --max-users 500 --max-duration 600 \
  --stages 100,250,500 --stage-seconds 120 --ramp-seconds 30 \
  --baseline-seconds 30 --scenario same --media-ids /tmp/playback-same.json \
  --search-query "$REAL_SEARCH_QUERY" --background-users 5 \
  --browse-interval 5 --search-interval 15 --seek-interval 30
```

For the second run change to `--scenario distinct --media-ids
/tmp/playback-distinct.json`. Allow a cool-down and check recovery between runs.
Optionally `--output /tmp/playback-same-report.json` writes a credential-free
report; copy it out afterwards. Do not write reports into an archive mount.

Default execution has a 30s browsing/search baseline followed by
100 → 250 → 500 viewers, each with a 30s ramp and 90s plateau; smaller prefixes
are allowed but skipping straight to 500 is forbidden. Maximum stage duration
is 300s; ramp/baseline minimum 10s. The wall-clock cap includes asset preflight,
baseline, ramp, hold and cleanup. A slow preflight can exhaust it; increase the
explicit cap within 1800s, never disable the cap.

Each viewer requests one segment per **six seconds or slower**, consumes the
whole response in bounded chunks, and never issues overlapping/catch-up/retry
storms. Seek churn selects another actual segment every 30s with initial
jitter; distinct viewers start at different real positions. Each viewer also
requests playback metadata/playlist on navigation. Five additional browsing
clients issue real `/api/media` reads every 5s and real semantic `/api/search`
POSTs every 15s. Those five clients are separate from the 500-viewer cap and
are capped at 20. No ingest, reindex, mutation or AI-generation endpoint runs.

Reports distinguish preflight, baseline, each ramp and **steady plateau**.
Requests are assigned to the phase in which they complete. Metrics include
per-endpoint counts/statuses, failures, timeouts, full-response p50/p95/max,
received bytes, segment deadline misses, seek count and successful-segment
throughput. MPEG-TS packet boundaries/sync bytes are checked (not full audiovisual
decode). Error response bytes are included only in raw byte counts: a failing run
is never evidence of useful throughput. P95 includes errors; inspect statuses
and success counts alongside it. Bytes are discarded, not saved to disk.

## Safety monitors, stop conditions and acceptance

The harness automatically stops if failures exceed **5% in a rolling window of
20–100 completed requests**, on the wall-clock cap, or SIGINT/SIGTERM. 401,
404, 416, 429, 503, truncated/empty/oversized bodies and timeouts are failures.
It does not retry or escalate concurrency after a failing stage. Exit 2 means
aborted; exit 0 alone is **not** proof of capacity.

Host CPU, RAM, network, SMB and worker health must be monitored **externally**;
the load-generator container cannot reliably assess another host. Keep a second
operator terminal; sample at least every five seconds with existing tools such
as `docker stats`, host `/proc/stat`, `/proc/meminfo`, interface byte counters
and PostgreSQL activity. Do not install monitoring tools or start workloads as
part of the benchmark. Stop with Ctrl-C/SIGTERM if any of:

- host aggregate CPU exceeds **85% of all 32 CPUs for 30s** (Docker's per-core
  totals may reach 3200%; do not confuse 100% of one core with host saturation);
- host `MemAvailable` falls below **20 GiB**, playback memory exceeds 80% of its
  configured limit, persistent RSS growth occurs, or any OOM/restart appears;
- normal browsing/search p95 exceeds **2× warmed baseline for 30s**, database
  connections approach 80% of the configured limit, or SMB errors/mount stalls
  appear;
- an ingestion/worker queue that should be idle unexpectedly grows, unrelated
  production users arrive, or network utilization crowds out other services.

Do not proceed to the next ramp when an external guard trips. Revoke the
short-lived session in `finally` even if interrupted. For an app session token
in the environment, existing API auth can revoke it without displaying it:

```sh
docker compose exec -T -e PLAYBACK_LOAD_TOKEN api python - <<'PY'
import asyncio, os
from app.auth import delete_session
from app.database import AsyncSessionLocal
async def revoke():
    async with AsyncSessionLocal() as db:
        await delete_session(db, os.environ["PLAYBACK_LOAD_TOKEN"])
        await db.commit()
asyncio.run(revoke())
PY
unset PLAYBACK_LOAD_TOKEN
```

Acceptance at every plateau: **<1% failures/timeouts**, segment p95 **<3s**
(required hard deadline <6s), <1% six-second deadline misses, browse p95 **<1s**
and search p95 **<3s**, both no worse than **20% above warmed baseline**.
No mount errors, orphan codec children, persistent file writes, OOMs, DB pool
exhaustion or monotonic memory growth. Recovery within 60s after stop must
restore baseline latency, CPU and connections; bounded TTL RAM caches may
remain until eviction. A 90s plateau is a pilot, not a long-duration SLA proof.
Repeat the maximum permitted 300s stage and independent browser playback
checks only after all guards pass.

### Bandwidth target: approximately 1.1 Gbps

The encoding profile is roughly **2.0 Mbps video + 0.192 Mbps audio**.
500 sustained viewers therefore require approximately **1.096 Gbps**
(137 MB/s) of useful payload; MPEG-TS/TCP/Ethernet overhead needs additional
headroom (plan at least 1.3 Gbps measured capacity). A 1-GbE link cannot meet it.
Variable-bitrate/simple content can measure lower; this is a sizing target,
not a fabricated measured result. Same-clip cache hits reduce CPU/SMB reads,
**not the 500 clients' outbound bytes**. Distinct/seek-heavy playback may fail
CPU/SMB limits well before reaching network bandwidth.

A generator inside the API container exercises real HTTP/auth/nginx routing
and measures application throughput, but same-host Docker traffic may bypass
the physical NIC. **It cannot prove 1.1-Gbps LAN/SMB throughput.** Use a separately
authorized client host on the intended network path for that claim, or report
the result explicitly as internal-network-only. Never send media to an
unauthorized external host.

## Regression checks (no deployment)

```sh
python3 -m unittest discover -s services/api/tests -p 'test_playback_load.py' -v
PYTHONPATH=services/api python3 -m unittest discover -s services/api/tests -p 'test_playback_service.py' -v
```

Service tests need the existing API runtime dependencies and an async
`DATABASE_URL`; they mock DB operations and do not contact production DB.
They cover auth, exact route registration, absent model/main imports, snapshot
immutability, close-before-probe/stream, range rejection and legacy routing.
Load tests are offline fake-transport tests covering target acknowledgement,
user/time limits, ID validation, routing regex, metrics, truncation, bounds and
abort behavior. Real 100/250/500 measurements are an operator action, not
asserted by unit tests or by supplying this implementation.