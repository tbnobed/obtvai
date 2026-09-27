# Production verification and networking

**GPU safety:** the RTX PRO 4500 failed a production face-detection task in
NVIDIA's PTX compiler despite passing post-update Whisper probes. Its service
is behind the `quarantined-gpu` profile on the second host; the RTX 5090 remains
active. Do not re-enable it merely because a transcription or matrix test
passes. Diagnose and exercise the face/embedding backend too. The affected
Celery failure was explicitly reconciled with its job record; normal bounded
catalog recovery remains responsible for retries once other stages finish.

The optimized deployment uses `obtv-efficiency-worker:verified`. To build the
small update without replacing CUDA/Torch, run:

```
docker build -t obtv-efficiency-worker:verified \
  -f deploy/remote-ingest/efficiency.Dockerfile services/worker
```

On the second host, use `--build-arg WORKER_BASE=obtv-ingest-worker:verified`.
Full future worker builds can also populate the efficiency image; retain
`efficiency.compose.yml` when recreating these services. Do not reset the
second host to the older image or remove its remote-inference flag.

The admission ceiling is separately controlled by
`CURATOR_CATALOG_ACTIVE_LIMIT` in the main server's `.env` and the
remote-ingest override. Default remains 3; the optimized deployment uses 4,
with one admission per minute and exactly two remote-inference slots. This is
a bounded initial setting, not proof that larger limits are safe or faster.

The second host's old DAC profiles matched the previous card's MAC addresses.
They were repaired and verified against actual ARP peer replies. Main-server
DAC is 192.168.102.2; the second server is 192.168.102.1. Spark's separate
second-server-facing link uses 192.168.100.1 with the second server at
192.168.100.2. Spark's main-server-facing address remains 192.168.101.1.
Both private links pass 9000-byte MTU tests. Existing default routes are
unchanged. Second-host LLM/caption requests use its direct Spark connection.

The second-host Mellanox ports negotiate 40 Gbps, but the PCIe link reports
8 GT/s ×1; a four-stream TCP test delivered about 6.9 Gbps. Keep bulk storage,
database and broker relays on the existing 10 Gbps LAN until the hardware
bottleneck is resolved and measured again. Do not infer usable bandwidth
from the Ethernet link speed alone.

# Bounded remote inference lane

`efficiency.compose.yml` is opt-in. Append it after the existing base, archive
artifact, archive-memory and remote-ingest overrides. It does **not** alter
video-only discovery/admission, the cutoff, admission rate, retry budget, or the
three-asset in-flight ceiling. Do not raise those until measuring the new lane.

## Why this change

The production two-hour measurement supplied during deployment showed these
average **successful stage** durations:

| Stage | Mean seconds |
| --- | ---: |
| Sentiment | 341 |
| Creative | 86 |
| Identify | 60 |
| Transcribe | 48 |
| Analyze | 40 |
| Diarize | 39 |

These are neither end-to-end asset durations nor a throughput forecast: stages
overlap, sample counts differ, and failures are excluded. In remote LLM mode,
the long text stages occupy GPU worker slots while waiting for HTTP responses.
Moving those stages releases the slots; it does not make Spark generate faster.

The new worker consumes only `llm`, uses prefork (preserving terminate/revoke),
prefetch 1 and **concurrency 2** initially. The launcher accepts only 1–4, and
refuses startup without both `REMOTE_LLM_QUEUE_ENABLED=1` and `LLM_BASE_URL`.
Run exactly one instance initially: scaling replicas multiplies the limit.
API requests and other callers outside this lane are not globally rate-limited
by this change; include them when assessing Spark load.

Analyze, creative, sentiment and identify use the lane only when both flags
indicate remote inference. Identify uses existing numeric embeddings on CPU;
actual face/voice embedding generation remains on GPU. Profile regeneration
uses the same remote/local selection. If remote inference is disabled, these
stages remain GPU-routed. Remote HTTP errors remain errors, never a silent
17-GB local-model load on the CPU worker.

## Identity, cancellation, and pipeline invariants

Video analysis already dispatches asynchronous child stages. Image ingestion's
synchronous bound embedding/caption `.apply(..., task_id=stage, throw=True)`
calls are unchanged; changing their queues alone would not free the parent.
The selected text stages are not synchronously invoked by the ingest pipeline.

Worker-created text tasks choose `llm` directly. API clients or older producers
may still explicitly specify `gpu`; the upgraded task's `before_start` replaces
that delivery with the same task ID, original args/kwargs and retry count, using
Celery's replacement protocol to retain callbacks, chains and root identity.
It never waits for a child result on the GPU worker.

The processing-job task identity is persisted **before** the replacement is
published, without claiming the job is running or successful. Each hop checks
for missing, cancelled or already-successful jobs. Cancellation can therefore
find the same ID during handoff, and the destination checks persisted
cancellation even if the broker revoke raced with dispatch. In-flight workers
still need the normal prefork terminate/revoke path.

Celery remains **at-least-once**, not exactly-once. A sender crash between
publication and acknowledgment can duplicate a replacement; completed-job
checks suppress sequential repeats, but they alone do not serialize two
simultaneously executing copies. Operators must retain the existing recovery
and reconciliation rules; do not purge queues or manufacture raw Redis task
messages. Tests exercise the real Celery tracer/protocol, not mocked `.run()`.

## Required deployment order

1. Keep video-only `CURATOR_CATALOG_ASSET_TYPES=Media`. Pause **catalog admission**
   first, not running work. Preserve every existing Compose override and mount.
2. Snapshot current container image IDs, service commands and nonsecret queue
   settings. Build the worker image and run tests in a disposable container
   with no production broker/database environment:
   `PYTHONPATH=/workspace/services/worker python3 -m unittest discover
   -s /workspace/services/worker/tests -p 'test_inference_queue.py'`.
   Run the existing creative-empty and catalog-media regressions too.
3. Start the new `worker-llm` using `--profile efficiency`, with a verified
   reachable OpenAI-compatible `LLM_BASE_URL`, concurrency 2, and the updated
   image. Verify its `llm` queue, ping, and a bounded inference request before
   enabling producers. It has no GPU device reservation, no GPU visibility,
   no beat, and no public listener.
4. Drain every existing GPU consumer, including the second host. Cancel
   consumption of `gpu` on the exact node names, then repeatedly inspect both
   **active and reserved** work until empty. Do not terminate active inference
   merely to speed deployment. An unresponsive inspect response is not "empty."
   If reserved tasks exist, let them finish; do not purge them.
5. Recreate drained GPU workers with the new image and
   `REMOTE_LLM_QUEUE_ENABLED=1`, preserving GPU IDs, concurrency 1, storage,
   shared broker/database and existing remote service ownership. The external
   host is **not** configured by this Compose file: explicitly update its
   worker environment/config before restarting. Keep the verified direct
   Spark URL for that host rather than replacing it with a main-host address.
6. Upgrade the CPU producer/consumer too, draining `cpu,ingest` safely before
   recreation. It runs embedded beat: stop the old instance before starting its
   replacement so two beat schedulers never overlap. Do not alter its NVENC
   reservation or archive mounts. Existing queued explicit-GPU text stages
   will be safely forwarded by upgraded GPU workers.
7. From **every main and remote GPU worker**, verify that importing
   `tasks.inference_queue.inference_queue()` returns `llm`, and that its
   effective `LLM_BASE_URL` is the intended endpoint. Do not print credentials.
   This is the required environment guard; no remote `.env` is automatically
   rewritten here. Mismatched producer/consumer configuration can cause
   bouncing or leave old workers occupied with remote waits.
8. Confirm all intended consumers are online and storage preflight still
   passes, then resume video-only admission. Observe real job IDs and successful
   completions through analyze → creative/sentiment. Verify those execute on
   `llm`, while transcription, diarization and embeddings execute on `gpu`.
   Check queue depth, oldest wait, Spark request latency/errors, stage duration
   and **completed videos/hour** before changing any concurrency limit.

`worker-llm` extends worker-graphics only to reuse its common environment,
dependencies and non-GPU setup. The base artifact volume and source mounts
are inherited, and this override explicitly mirrors all seven archive artifact
bind mounts; it does not consume graphics work or call ComfyUI. Validate the
fully merged Compose configuration rather than assuming sibling service
overrides are inherited.

## Rollback and remaining bottlenecks

Stop new admission, drain the `llm` lane and active work before removing its
consumer. Roll back producer flags/images only after queued remote work is
accounted for. Keep the llm consumer running while disabling producers if
draining requires time. Never orphan a populated `llm` queue or purge it.
On rollback, a CPU-only llm worker must not be configured for local-model mode.

Do not promise a fixed speedup from this change. Spark may now be the explicit
bottleneck rather than hidden waiting on GPU workers. Direct Spark links can
reduce transport dependency, but do not accelerate token generation. Measured
server-to-server DAC throughput was about 6.88 Gbps because of the second
host's PCIe link, below its existing 10-Gbps LAN; retain the existing bulk
storage path rather than moving it merely because a DAC cable is present.