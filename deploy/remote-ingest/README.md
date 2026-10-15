# Remote ingestion workers

The main server remains authoritative for catalog admission, PostgreSQL, Redis,
Qdrant, original media, and derived outputs. Remote GPU workers do not run a
second catalog runner, watcher, or application database.

## Deployed configuration

The operator-managed configuration is intentionally outside the repository:

- Main server: `/opt/obtv-remote/compose.json`, gateway build sources and image
  staging directory. The gateway attaches to the existing application network.
- Remote worker host: `/etc/obtv-remote/compose.json`, root-only `worker.env`,
  restricted SSH identity, pinned host key, and SMB credential file.
- Remote systemd services: `obtv-main-tunnel`, `obtv-remote-storage`,
  `obtv-remote-workers`.

Do not copy those private configuration files into the repository or logs.
Gateway source is in this directory; production connection details are held
in the operator configuration.

## Network and storage contract

Database, broker and vector service relays bind **only to main-host loopback**.
An authenticated SSH connection forwards them to remote-host loopback. The SSH
key has no interactive shell, a fixed SFTP command into the bounded gateway
container, and an explicit forwarding destination allowlist.

The gateway resolves Docker service names on every connection so rebuilding
PostgreSQL/Redis/Qdrant does not leave stale container IPs in a remote worker.
Ancillary model services are forwarded too; preserve their configured model
names rather than loading a different encoder or a local LLM.

Source `/curator` is a read-only bind of an actual CIFS mount. Derived archive
directories are writable CIFS binds from the same share as the main server.
On the rebuilt host, storage uses the first X550 port (`enp8s0f0`), configured
by `/etc/netplan/60-obtv-storage.yaml` with DHCP and no DHCP routes or DNS.
Specific persistent routes reach `10.81.100.220/32` and `10.63.13.101/32`
through storage gateway `10.10.0.1`. Both shares are mounted directly over
private SMB, retaining `nosharesock`, the existing credential file, and the
read-only media2 mount. SMB is not exposed publicly.
Other `/artifacts`, `/media`, and `/uploads` paths use the same bounded SFTP
filesystem through main-server storage address `10.10.1.94`, with
`HostKeyAlias=192.168.200.165` to verify the existing pinned host identity.
Do not substitute empty local directories.

The management default route remains on `enp5s0` for SSH/internet and the
database/broker/model tunnels. The storage startup script requires all three
storage destinations to route through `enp8s0f0`, failing closed rather than
silently reverting to management. The former SMB tunnels remain available
for deliberate rollback but are no longer used by the mounts.

Worker startup verifies actual mounts and performs the existing archive
write/read/remove probe before starting Celery. Docker restart policies are
disabled for these workers: systemd owns startup ordering so workers cannot
start before shared storage is mounted. Source binds disallow automatic
creation of missing host directories.

Each GPU runs one prefork Celery child with prefetch one. Workers use the
verified main-worker image, production model configuration, and a local model
cache. Do not rebuild against floating CUDA/PyTorch packages independently.

## Operations

### CPU ingestion on the rebuilt host

`obtv-remote-cpu.service` independently supervises
`/etc/obtv-remote/cpu-compose.json` (project `obtv-main-ingest-cpu`).
It runs two prefork slots consuming only `cpu-ingest`, without beat or GPU
devices, with an eight-CPU quota, 16-GiB memory limit, and the same existing
CPU affinity restrictions as the GPU workers. It uses the verified image and
the same 10-Gb shared mounts. It does not consume the general `cpu` or `ingest`
queues: general rendering/publishing and writable-upload imports stay on main.

Stage `ingest_cpu_app.py` from this directory at
`/opt/obtv-ingest-checks/ingest_cpu_app.py` on both hosts before deployment.
The main CPU entrypoint in `efficiency.compose.yml` annotates ingestion
preparation tasks to publish their children to `cpu-ingest`, which both main
and remote CPU workers consume. Main retains the only embedded beat scheduler
and also consumes `cpu,ingest`. GPU/API producers retain their existing routes;
this is incremental offload, not a global reroute of every CPU job.
`check_cpu_routing.py` validates final publish options without broker writes
when run inside the verified worker image with that entrypoint available.

Before storage remounts, drain and stop **both** `obtv-remote-workers` and
`obtv-remote-cpu`; both services hold bindings to the shared mounts.
For CPU maintenance, drain only `remote-cpu@obtvai-ingest2` and use its separate
service. Do not restart both GPU workers just to change CPU capacity.

On the remote host:

```sh
sudo systemctl status obtv-main-tunnel obtv-remote-storage obtv-remote-workers
sudo docker logs --tail 50 obtv-main-ingest-gpu0
sudo docker logs --tail 50 obtv-main-ingest-gpu1
```

The queue is controlled by `REMOTE_GPU_QUEUES` in the root-only Compose `.env`.
Use an isolated queue for initial readiness checks, then `gpu` for normal
processing. Confirm both workers are online through Celery inspection and
verify a real main-database job completed on each node.

Before stopping/updating workers, inspect active tasks and let them finish.
The service uses a long graceful-stop window; do not kill running jobs or purge
queues. Retain the previous worker image until real processing passes.

The older standalone installation on the remote machine is preserved.
Its GPU and graphics workers must remain stopped while these GPUs serve the
main archive. Do not delete its databases, caches, or media.

Catalog concurrency is separately controlled on the **main** runner. Extra
workers do not bypass the date cutoff, retry budgets, quarantine, persistent
infrastructure pause, storage reserves, or per-asset locks. Increase admission
only after storage, GPU and real-job checks pass; never start a second runner.

`remote-ingest.compose.yml` raises the main runner ceiling to three in-flight
assets while retaining one new admission per minute. Include this override in
future runner recreations or the original one-asset ceiling will return.
Include `archive-memory.compose.yml` too when managing the full stack, and never
use `--remove-orphans` to remove separately managed services.

The worker image's Celery uses `python3`; its separate `python` interpreter does
not have the GPU packages. Use `python3` for diagnostics and startup probes.

## Host stability and recovery

GPU reservations must also have explicit Docker `devices` mappings for the
selected card's `/dev/nvidiaN`, `/dev/nvidiactl`, `/dev/nvidia-uvm`, and
`/dev/nvidia-uvm-tools`. A systemd daemon reload revoked device access from
the legacy NVIDIA-runtime containers while already-initialized processes
kept doing some work; fresh processes failed NVML/CUDA initialization and
Whisper model loads reported OOM despite ample host-visible VRAM.

After provisioning, run `pin-gpu-devices.py` against the root-only remote
Compose configuration, then recreate gracefully drained GPU workers.
It resolves device minors from the configured UUIDs. Do not expose both
cards to each worker or grant privileged mode. Check `nvidia-smi -L` inside
each container both before and after a controlled `systemctl daemon-reload`,
then verify real speech decoding, not just model load or a silent VAD sample.
The CPU service remains independent and needs no NVIDIA devices.

The standalone API can reserve substantial GPU memory even when its standalone
GPU workers are stopped. Check `nvidia-smi` process ownership, not just Celery
queues, before dedicating this host to ingestion. Its API is intentionally
stopped with Docker restart disabled; its data remains intact.

The rebuilt host uses Netplan/systemd-networkd. The following describes the
older, pre-rebuild installation only: on that NetworkManager-managed host,
networkd had no managed interfaces.
Its redundant wait-online service is disabled. NetworkManager's wait checks
connectivity rather than waiting indefinitely for every unused connection
profile to finish activation. Neither change modifies the active IP or routes.
The unrelated CaptionForge NFS mount is on-demand, `nofail`, with a bounded
mount timeout, so its unavailable server cannot hold up login during boot.

For GPU diagnosis, drain remote consumers and confirm no active tasks before
stopping workers. Run `gpu-check.py` inside the exact worker image, exposing one
GPU at a time. It checks storage, CUDA allocation/computation, and two cached
Whisper load/inference/release cycles against a short existing audio excerpt;
it does not change application records. A passing probe is not a soak test.
Keep failed GPUs behind an opt-in Compose profile until retested.

NVIDIA kernel Oops/soft-lockup or PTX compiler crashes require host-driver
investigation, not blind Torch upgrades in the worker image. Preserve the CUDA
and FFmpeg compatible driver branch when applying a host-driver patch. Drain
workers before installation and reboot before comparing results: mixing the
old loaded kernel module with new userspace libraries is not a valid test.