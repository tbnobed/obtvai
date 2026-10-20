---
name: Remote GPU ingestion
description: Cross-host storage/network constraints and worker-image interpreter pitfall.
---

The user wants the rebuilt second server to transition from ingestion-only to user-facing translation and other GPU-heavy processing.

**Why:** The user wants better interactive performance and benchmark evidence before deciding whether a larger CPU server is necessary.

**How to apply:** Keep the main server authoritative for scheduling and data; do not install a second standalone app/database. The broader role requires explicit queue routing and verification of writable outputs and source access, not merely subscribing existing ingestion containers to more queues.

For the secondary's interactive role, use local MADLAD transcript translation
rather than sending translation back to Spark by default.

**Why:** The chosen implementation reserves secondary GPU capacity for user
work and removes Spark as a dependency for transcript translation. This is an
engine/quality tradeoff, not merely a queue change; short Spanish smoke tests
do not certify every language or long-form translation quality.

**How to apply:** Preserve this deliberate separation unless requirements
change. Keep other Spark-backed analysis routes intact and benchmark translation
quality before promising parity with the former LLM translation path.

CPU offload must be ingestion-only, with main-server fallback and no second scheduler.

**Why:** The shared CPU queue also carries rendering/publishing work, while remote uploads are read-only. Consuming the existing general queues would violate the second server's ingestion-only role or fail upload imports.

**How to apply:** Isolate preparation work, retain main consumers, and preserve GPU queues and CPU-affinity containment. Drain both remote CPU and GPU consumers before changing shared mounts.

The intended network layout is a 10-Gb NIC on the storage VLAN; the 1-Gb NIC is only for SSH and internet access.

**Why:** The user explicitly corrected the assumption that the management connection was the intended storage path.

**How to apply:** Verify storage interface configuration and actual routes after rebuilds. Preserve the management default route. A working storage relay over management is temporary connectivity, not completion of the intended storage setup.

Select worker GPUs by UUID or verified PCI identity, not inherited numeric indices.

**Why:** After the rebuild the RTX PRO 4500 and RTX 5090 enumerated in the opposite order. Reusing old index-based assignments would assign the previous containment policy to the wrong card.

Remote ingestion must retain the main server's identical paths, backing shares,
models, and authoritative broker/database. Do not make a second independent
ingestion database or expose broker/database ports publicly.

**Why:** During initial provisioning the added GPU host reached the main LAN but could not directly reach the
archive SMB networks. This is not a permanent network constraint: the intended storage VLAN must be checked after installation. Archive admission validates actual CIFS backing and
read-only source mounts, so an SSHFS-only copy of the archive would fail closed.

**How to apply:** Use verified direct storage-VLAN CIFS and bounded SFTP mounts for bulk data; keep encrypted loopback relays for broker/database/model traffic. Fail closed if storage would silently revert to management. Preserve the old relays only for deliberate rollback.
See `deploy/remote-ingest/README.md` for the operational configuration locations.
Preserve the remote host's old standalone data; its GPU workers must not compete
with the main-ingestion workers.

Use `python3`, not `python`, for checks inside the production worker image.

**Why:** The running Celery executable uses `/usr/bin/python3` and its installed
Torch stack, while the image's `python` resolves to a different interpreter
without Torch. A failed `python -c 'import torch'` therefore does not establish
that the image lacks GPU dependencies.

**How to apply:** Inspect the Celery shebang before diagnosing dependency
failures; do not reinstall Torch over the working image to fix this mismatch.

Test the actual inference engine as well as CUDA computation when diagnosing
GPU stability, and distinguish kernel faults from user-space model failures.

**Why:** On the added Blackwell host, a CUDA matrix/allocation test passed but
Whisper crashed in NVIDIA's PTX JIT compiler. Earlier logs showed a kernel NULL
pointer fault in the NVIDIA module followed by CPU soft lockups. After a driver
patch, repeated Whisper tests passed but production face detection still
crashed in the PTX compiler. A cache-disabled pass alone also did not establish
a root cause. Passing one inference engine does not validate another's JIT path.

**How to apply:** Drain consumers before driver maintenance; preserve the
CUDA/FFmpeg-compatible branch, reboot to load matching kernel/userspace driver
versions, test GPUs separately across transcription AND face/embedding
engines with repeated load/inference/release cycles, then confirm real work.
Never claim a short test proves an intermittent failure is permanently fixed.

Compare CPU affinity before attributing an NVIDIA JIT crash to a GPU card.

**Why:** The same isolated 4500 face/JIT workload repeatedly crashed on logical
CPU 11 and passed on CPUs 0, 10, and 12; the 5090 also suffered a face crash.
CPU-only compression/hash checks passed, so this does not establish defective
CPU silicon. Excluding CPU 11 and its sibling allowed repeated face and Whisper
probes to pass, but is containment rather than proof of a repaired host.
A subsequent actual-frame mixed-workload soak crashed on CPU 9 despite that
restriction, while a CPU-0-only actual-frame control passed. Excluding 10–11
is therefore explicitly insufficient to clear the host or restore the 4500.

**How to apply:** Keep identical GPU/model/runtime inputs, fresh caches, and
bounded CPU-affinity A/B tests. Preserve host-specific worker CPU restrictions
until the underlying fault is diagnosed; do not declare the card defective or
clear the host based on generic CUDA/CPU tests. A rebuilt host may resume
bounded production after repeated mixed inference and real-job verification,
but that does not justify removing containment or declaring the old fault fixed.
See `docs/4500-diagnostics.md` for the latest qualification status.
Exercise actual detected faces: blank synthetic frames do not execute
landmark and demographic submodels even when the models load successfully.

Do not move bulk traffic to a DAC solely because its negotiated link is faster.

Qualify both secondary DAC ports concurrently, and distinguish hardware
receive drops from TCP retransmissions and intentional pacing.

**Why:** Queue-level RX missed/drop counters stayed flat while the Intel
`port.rx_discards` counter increased substantially. Enabling RX/TX Ethernet
flow control eliminated the measured port drops in concurrent tests and
allowed removal of the temporary 20-Gbit software cap. Some TCP
retransmissions remained, so zero port drops is not a loss-free guarantee.

**How to apply:** Include Intel port-level counters, not only queue counters,
and baseline them after configuration changes that may reset statistics.
Preserve verified RX/TX pause support on both secondary DACs. Change link
autonegotiation with ethtool -s, not -A; wait for carrier and settled pause
readback before declaring success or failure. A transient readback showed
off before the driver reported RX/TX enabled. Do not retain a firmware-LLDP
change merely because it was tried: default LLDP was restored for qualification.
Do not promise two independent 40-Gbit streams through a shared PCIe path.

**Why:** Before the rebuild, the second host's 40-Gbps ports were constrained
by a PCIe ×1 path and measured below the 10-Gbps LAN. That old bottleneck is
not a current hardware constraint: post-rebuild verification found a wider
PCIe path and substantially faster direct-link throughput.

**How to apply:** Check PCIe width/speed and measure throughput before migrating
storage; revalidate after hardware rebuilds rather than carrying forward old
slot limitations. Direct, low-volume inference traffic can still avoid relay
hops. A passing throughput test is not sufficient qualification: compare NIC
error counters before/after load, and verify application routes separately
from IPv6 link-local cable tests.

Do not promote the secondary–DGX direct link to production inference merely
because it responds or benchmarks quickly.

**Why:** Qualification after restoring direct addressing found increasing
physical CRC/PCS errors. Jumbo frames caused a severe one-direction throughput
collapse; matching 1500-byte MTUs restored speed but did not cure the errors.

**How to apply:** Keep that pair at the conservative matching MTU until cable/port
replacement and a clean error-delta load test. Check `docs/direct-link-qualification.md`
before migrating inference. The server-to-server link also needs receive-drop
qualification; increased rings alone did not make it loss-free.