---
name: Phantom running jobs after worker restarts
description: Why deploys leave jobs stuck "running" and how the stale-job reaper must be designed
---

Rebuilding/restarting a Celery worker container mid-task kills the task process; nothing updates the job row, so the UI shows a phantom "running" job forever (0% GPU, idle DB — looks like a hang but is a dead task).

**Why:** status transitions are written only by the task itself; a SIGKILLed prefork child never runs its error handler.

**How to apply:** diagnose with py-spy from a sidecar (`docker run --pid=container:<id> --cap-add SYS_PTRACE python:3.11-slim`, use /proc not ps). A reaper must be multi-signal and conservative: task id absent from celery inspect (active+reserved+scheduled) for 2+ consecutive cycles AND stale heartbeat, skip cycles with no inspect replies — a single missed broadcast reply from one busy worker is normal, and a falsely reaped job can be retried into duplicate execution.
