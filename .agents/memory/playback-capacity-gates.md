---
name: Playback capacity evidence
description: Distinguish shared-clip cache capacity from independent-viewer encoding capacity.
---

Do not certify concurrent playback from same-clip tests alone. Always separately
test distinct clips and cold source versions, with ordinary application traffic.

**Why:** Shared-clip reuse handled 500 synthetic viewers, while distinct content
hit overload during the first ramp toward 100. Internal delivery throughput
does not establish Internet egress or real-browser performance.

**How to apply:** Use controlled ramps with failure/resource cutoffs and report
the highest fully completed workload, test duration and authentication model.
Preserve the RAM-only playback constraint unless the user explicitly changes it.