---
name: ffmpeg progress parsing in worker tasks
description: How to run ffmpeg with live progress reporting from Python without deadlocks
---
Rule: when running ffmpeg from Python with progress reporting, use `-progress pipe:1 -nostats`, launch with `Popen(stdout=PIPE, stderr=STDOUT)`, and parse `out_time_ms=` lines (value is MICROSECONDS despite the name — divide by 1_000_000).

**Why:** reading stdout while stderr is a separate un-drained pipe deadlocks once ffmpeg fills the stderr buffer; `subprocess.run(capture_output=True)` gives no live progress at all. A post-loop `proc.wait(timeout=...)` does not bound the read loop — enforce a wall-clock deadline inside the loop and kill the process on timeout.

**How to apply:** any worker task wrapping ffmpeg/long subprocesses that must update job progress in the DB. Throttle DB progress writes (e.g. every 5%). Keep a bounded deque of non-progress lines for error tails since stderr is merged.
