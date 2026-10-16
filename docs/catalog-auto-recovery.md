# Bounded remote-model recovery

The recurring apply runner records new, explicitly identified remote-model
transport failures as recoverable pauses. Legacy/operator pauses and mixed
hardware/storage failures are fail-closed and require operator review.

- Probes after 1, 2, 5, then every 10 minutes (delays between failed probes,
  rounded to the scheduler interval). A successful probe schedules confirmation
  one minute later. Every probe performs real generation with a 45-second total
  deadline; there is no local-model fallback.
- Two consecutive successes trigger reconciliation under the catalog admission
  lock. A newly discovered unsafe failure prevents resumption.
- One video is admitted with existing original-air-year ordering, attempt
  budgets, storage checks and concurrency limits. Further admissions wait for
  fresh successful analysis with an `Analysis complete:` log, not a skipped
  no-transcript analysis. Running jobs are never stopped.
- Failed/stalled validation after 30 minutes requires review. Three distinct
  model outages within one hour also lock automatic recovery.
- After 30 minutes unavailable, an alert appears in the existing admin catalog
  runner error display and structured runner logs; probes continue unless locked.
  These are in-app/log alerts, not email/SMS notifications.
- State, probe deadlines and outage history survive restarts in the existing
  runner checkpoint. No schema migration is needed. Explicit admin Resume
  acknowledges/reset recovery and GPU circuit state under the admission lock.

The safety policy does not clear authentication/configuration failures, storage
failures, GPU faults, or legacy manual pauses. Probe HTTP 408/429/5xx temporary
statuses can continue retrying an already eligible transport outage; an initial
HTTP error is conservatively not auto-enrolled.

## Deployment and verification

Deploy both the API and catalog runner from the same updated API image; workers
do not need restarting. Preserve all compose overlays, active limits, paths and
the 2026 priority. Production currently uses a derivative image named
`obtv-api-auto-recovery:verified`; future builds must include these source files.

Run catalog tests with aiosqlite in an isolated test container, never against the
production database. Recovery tests cover durable probe sequencing, lock
contention, unsafe failure precedence, authentication rejection, alerts, and
single-asset validation including stale/skipped analysis.
