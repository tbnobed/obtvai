---
name: Remote GPU ingestion
description: Cross-host storage/network constraints and worker-image interpreter pitfall.
---

Remote ingestion must retain the main server's identical paths, backing shares,
models, and authoritative broker/database. Do not make a second independent
ingestion database or expose broker/database ports publicly.

**Why:** The added GPU host reaches the main LAN but cannot directly reach the
archive SMB networks. Archive admission validates actual CIFS backing and
read-only source mounts, so an SSHFS-only copy of the archive would fail closed.

**How to apply:** Preserve the encrypted loopback relays, actual CIFS mounts
through forwarded SMB ports, and bounded SFTP mounts for other shared paths.
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
pointer fault in the NVIDIA module followed by CPU soft lockups. R580's patch
update resolved the reproducible short test, but that is not proof of prolonged
stability. A cache-disabled pass alone also did not establish a root cause.

**How to apply:** Drain consumers before driver maintenance; preserve the
CUDA/FFmpeg-compatible branch, reboot to load matching kernel/userspace driver
versions, test GPUs separately with repeated Whisper load/inference/release
cycles, then confirm real work. Never claim a short test proves a long-duration
intermittent failure is permanently fixed.