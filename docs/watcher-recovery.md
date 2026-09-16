# Watcher recovery and safe rollout

The watcher must report the liveness of each polling emitter, not just its
container or watchdog dispatcher. An SMB snapshot error can stop one emitter
without terminating either of those processes.

The image health check reads `/tmp/watcher-health.json` locally. It requires
`healthy: true` and an `updated_at` epoch timestamp no older than 180 seconds.
Missing, malformed, stale or degraded heartbeats fail the check. The heartbeat
must reflect live per-root emitters and recent successful inbox reconciliation.
The check itself never accesses SMB, so an unavailable mount cannot block it.
Docker marks an unhealthy container but `restart: unless-stopped` does **not**
restart it merely for being unhealthy. Recovery is performed inside the watcher.
Startup or extended processing can temporarily make the heartbeat stale; inspect
logs and the heartbeat's per-root diagnostics before deciding to restart.

## Rollout precautions

No production restart or network-route change is part of this implementation.
Arrange an approved maintenance window before deploying the watcher image.

- The existing default `SCAN_ON_START=1` walks **all media roots** and can queue
  media ingest. API deduplication is not a reason to trigger this silently.
- To deploy without that broad scan, set `SCAN_ON_START=0` for the watcher in the
  deployment environment before recreating it. Confirm the effective Compose
  configuration and obtain approval for the restart. Periodic top-level XML
  reconciliation still recovers inbox requests; it is intentionally independent
  of media startup scanning.
- Rebuild/recreate only the watcher service, not the API or workers. Do not
  change mounts, SMB configuration, or the Curator/default network routes.
- After deployment, check the heartbeat, per-root recovery logs, and an approved
  test XML from submission through archival. During a controlled mount-error
  test, health should degrade, then recover once polling and inbox scans resume.
- Do not expect recovery to perform recursive media backfills. Files missed in
  media roots during downtime require a separately approved rescan.

## Local regression tests

Run `python -m unittest discover -s services/watcher -p 'test_*.py'`.
The tests simulate mount errors without mounting or interrupting production SMB.
When watchdog 6.0.0 is installed, the suite also exercises actual polling threads
for startup snapshot failures and runtime emitter death; those two integration
tests are explicitly skipped in dependency-free environments.

Archive-only retry state is process-local. A process restart after API acceptance
but before archival can resubmit the XML; the existing API deduplication remains
the protection for that boundary.