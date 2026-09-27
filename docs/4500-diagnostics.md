# Second-host GPU crash investigation — 2026-09-27 UTC

## Finding

The failure is reproducibly CPU-affinity-dependent, not isolated to the RTX PRO
4500. The 5090 also lost a production face-detection child with SIGSEGV.
Kernel reports associated both production failures with logical CPU 11.
This is evidence for a shared host/runtime problem, **not proof of defective
GPU or CPU silicon**.

Host: ASUS PRIME B760M-A AX, BIOS 1820 (2025-05-15), i9-14900KS,
active microcode 0x133, kernel 7.0.0-34-generic, NVIDIA 580.178.04.
Worker runtime: Torch 2.8.0+cu128, ONNX Runtime 1.22.0.

## Controlled tests

Disposable containers used the production worker image, only GPU 1, no network,
read-only copies of the existing buffalo_l models, and bounded memory/runtime.
No ingestion jobs or application records were created by these probes.

The direct ONNX tests used one intra/inter-op thread, disabled the CUDA disk
cache, and ran both SCRFD detection and ArcFace recognition with synthetic
inputs, three inferences per model. Each trial used a fresh container.

| Allowed logical CPU | Fresh trials | Result |
|---|---:|---|
| 0 | 2 | Both passed detection and recognition |
| 11 | 2 | Both SIGSEGV, exit 139, before detection completed |
| 10 | 2 | Both passed detection and recognition |
| 12 | 2 | Both passed detection and recognition |

An earlier full InsightFace trial also passed on CPU 0 and crashed on CPU 11.
After excluding CPUs 10–11, three fresh full InsightFace trials passed, each
running five detection/recognition cycles with CUDA providers verified.
The existing GPU/storage/Whisper probe then passed on the 4500 with that CPU
restriction: 30 seconds of CUDA allocation/compute, followed by two cached
Whisper load/transcribe/release cycles on a short existing audio excerpt.

A separate 20-second CPU-only compression/decompression/SHA256 test passed on
both CPUs 0 and 11. Therefore generic CPU corruption has **not** been established.
The failing combination remains the NVIDIA inference/JIT path and CPU affinity.
Synthetic face tests exercise execution, not face-recognition accuracy.

The reusable direct-ONNX reproducer is
`deploy/remote-ingest/face-jit-check.py`. Run it via stdin in an isolated worker
image container with `--network none`, `--gpus device=1`,
`--cpuset-cpus 0` (or the CPU being compared), `--memory 10g`,
`--pids-limit 96`, `-e OMP_NUM_THREADS=1`, `-e OPENBLAS_NUM_THREADS=1`,
`-e CUDA_CACHE_DISABLE=1`, and a read-only mount containing the cached
`/root/.insightface/models/buffalo_l` directory. Override the image entrypoint
to `python3 -u -`. Wrap each fresh container in an external timeout and remove
it afterward if timeout leaves it running. Never launch a Celery consumer for
these diagnostic tests.

## Applied containment

- Both remote GPU service definitions now have `cpuset: "0-9,12-31"`.
  CPUs 10 and 11 are sibling threads according to Linux sysfs; both are excluded.
- The 5090 was drained, restarted under that restriction, and resumed consumption.
- The 4500 remains behind the `quarantined-gpu` profile. Successful short probes
  are not sufficient to declare the host repaired.
- The confirmed failed 5090 job was conditionally reconciled to `error` after
  checking its Celery `FAILURE` result. Existing bounded catalog recovery owns
  retry scheduling; no duplicate stage or root task was manually published.
- No global CPU offlining, BIOS/voltage changes, driver replacement, reboot,
  database reset, or queue purge was performed.

Operator configuration remains in `/etc/obtv-remote/compose.json`; a root-only
backup precedes the affinity change. Do not restore the whole file over newer
settings or remove the quarantine as an incidental configuration cleanup.
The affinity restriction protects these containers, not every process on the host.

## Remaining diagnosis

### Follow-up mixed-workload test — 2026-09-27 04:46 UTC

The planned 15-minute soak **failed in its first cycle**. CUDA computation
passed, but full face inference on an actual completed-media frame crashed
with SIGSEGV. CPU affinity excluded 10–11 as intended; the kernel reported
the fault on CPU 9. Whisper and diarization were not reached in this run.
This invalidates any claim that excluding only 10–11 is sufficient.

A single targeted control run using only CPU 0 passed ten actual-frame face
iterations, including detection, both landmark models, gender/age, and
recognition. This strengthens the CPU-affinity association but does not prove
CPU hardware is defective or establish a safe production configuration.
Do not progressively exclude cores until a short test passes and call it fixed.

The read-only reproducer is `deploy/remote-ingest/gpu-soak.py`; it selects a
completed audio/proxy pair, extracts ephemeral samples, and exercises fresh
processes for CUDA computation, face inference, Whisper, and diarization.
Native stack reporting and per-model markers support subsequent diagnosis.
It never calls production Celery tasks. Use `--diagnose-face` for the short
actual-frame control and preserve a strict external container timeout.

The 4500 remains quarantined. The 5090 remains on its existing restriction;
its earlier stable period must not be interpreted as clearing the wider host
issue, especially across future cold model loads.

Review CPU/BIOS power and voltage settings against the board vendor's supported
Intel defaults; do not assume the current settings are incorrect. Run appropriate
CPU/RAM diagnostics in a maintenance window. If these remain clean, compare
supported driver/runtime combinations using the same CPU-0/CPU-11 reproducer.
Do not flash firmware or alter voltages speculatively.

Before restoring the 4500, run longer mixed transcription, diarization, and
face/embedding validation under containment, followed by monitored real work.
Retain containment until the CPU-affinity fault is understood and separately
validated; a passing CUDA matrix or CPU-only test does not clear the JIT failure.