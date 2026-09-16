---
name: Watcher SMB recovery
description: Watchdog polling can stop after a transient SMB failure while the container remains running.
---

Do not treat a running watcher container as evidence that all watched directories are still being polled.

**Why:** Production SMB reconnect failures coincided with missing polling threads and unprocessed Curator inbox XML. The installed watchdog PollingEmitter catches snapshot OSError by emitting a directory-deleted event and stopping its thread; it does not automatically recover when the share becomes readable again.

**How to apply:** Check per-root emitter liveness and reconcile inbox contents after recovery. A one-time startup scan cannot recover files missed while an emitter is dead. Separate transient mount failures from actual directory deletion, and preserve manifest stability checks, retry deadlines, and API deduplication when adding recovery.

Start the watchdog dispatcher independently of root scheduling; validate lifecycle
changes against the pinned watchdog version, not only fake observers.

**Why:** Watchdog 6 takes its initial polling snapshot synchronously when an
emitter starts. Scheduling roots before starting the observer lets one unavailable
root abort startup before the dispatcher thread starts. Replacing emitters alone
cannot recover an observer whose dispatcher never started.

**How to apply:** Tests should cover both an initial snapshot error and a later
polling snapshot error using real watchdog threads. Keep recovery limited to the
XML inbox; media-root startup rescans remain an explicit rollout consideration.