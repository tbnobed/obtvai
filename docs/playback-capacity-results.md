# Playback capacity gate — 2026-10-01

**Result: NOT approved for 500 viewers watching different content.**

Tested on the actual application host through nginx, using four CPU-only playback
replicas (two encoders, 32 deliveries, four CPU cores and 1 GiB memory limit each).
Requests used real archive clips, HLS segments, seeks, browsing and search.
This was a short synthetic test, not a long-running browser/Internet benchmark.

## Same clip

100 → 250 → 500 virtual viewers, five background clients, 210 seconds total.
At the 40-second steady 500-viewer stage:

- 3,299 segments, 40 browse requests and 10 searches; zero failures/timeouts.
- Segment p95 70 ms; browse p95 63 ms; search p95 745 ms.
- Useful video throughput approximately 1,095 Mbps inside the Docker network.
- No six-second segment deadlines missed.

This demonstrates memory reuse and internal delivery performance, not Internet
egress, 500 distinct authenticated users, actual browser rebuffering, sustained
ingestion contention, or 500 independent encodes.

## Different clips

All 500 selected clips passed metadata and playlist preflight. The live ramp
stopped after 16.4 seconds of the initial 100-viewer ramp: 73 viewers had issued
metadata requests. Six requests returned 503 (three metadata, three segments),
crossing the rolling >5% safety threshold. Overall ramp request failure rate
was 2.26%; these are different denominators, not contradictory results.

100 segments succeeded. Segment p95 was 3.12 seconds. Browsing/search continued
successfully (p95 79 ms / 958 ms). Playback processes returned to idle after
stopping; the earlier permanent slot leak did not recur.

## Next gate

Reduce fresh encoding cost or provision dedicated encoding capacity before
attempting a full distinct-content 500-viewer run. Investigate whether existing
Curator H.264 proxies can be repackaged without full video re-encoding while
preserving independent segment/seek boundaries and sidecar audio. Otherwise
benchmark isolated hardware encoding or additional dedicated CPU hosts.
Do not borrow ingestion GPU capacity without an explicit resource budget.

Repeat cold/warm distinct-content tests, then a sustained run with independent
sessions, real browsers, representative ingestion, and a remote load generator.
Keep the existing no-persistent-playback-copy constraint. Merely raising queue
limits or interpreting a same-clip cache hit test as certification is not enough.

## Rollout state

The isolated playback pool and bounded RAM reuse are live. The normal API was
not restarted. Frontend automatic overload recovery and manual Retry are live.
Four replicas were started with PLAYBACK_API_IMAGE=obtv-playback:scale,
PLAYBACK_REPLICAS=4 and PLAYBACK_MAX_WAITERS=256, appending playback.compose.yml
after the existing overlays. Preserve that complete overlay list for future
rollouts; omitting it can remove playback routing or change the replica count.