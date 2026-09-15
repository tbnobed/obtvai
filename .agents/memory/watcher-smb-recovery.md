---
name: Watcher SMB recovery
description: Watchdog polling can stop after a transient SMB failure while the container remains running.
---

Do not treat a running watcher container as evidence that all watched directories are still being polled.

**Why:** Production SMB reconnect failures coincided with missing polling threads and unprocessed Curator inbox XML. The installed watchdog PollingEmitter catches snapshot OSError by emitting a directory-deleted event and stopping its thread; it does not automatically recover when the share becomes readable again.

**How to apply:** Check per-root emitter liveness and reconcile inbox contents after recovery. A one-time startup scan cannot recover files missed while an emitter is dead. Separate transient mount failures from actual directory deletion, and preserve manifest stability checks, retry deadlines, and API deduplication when adding recovery.