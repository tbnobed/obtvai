---
name: Catalog failure pause ownership
description: Distinguish isolated asset retries from durable systemic pauses, and reconcile recovered jobs before retrying.
---

A systemic processing failure must persist an unacknowledged pause independently of the catalog run that first observes it. Dry runs and manual runs must not consume failure notifications intended for the recurring runner. Isolated asset failures instead use bounded retries and quarantine; one transient model-output failure must not stop unattended ingestion.

**Why:** Counting only new status transitions allowed a dry run to notice and mark a failed worker first; the subsequent recurring run then saw zero new failures and could continue admitting assets.

**How to apply:** Check the persistent pause before admission and require explicit acknowledgment to clear it. Test a manual/dry reconciliation followed by a recurring run. Resuming alone is not evidence that a runner is alive; report active discovery only after a real runner heartbeat.

**Recovery lesson:** Reconcile actual job states before enforcing an attempt budget. A failed stage may already have succeeded on a manual retry; do not replay the entire pipeline solely because its catalog row still says retry. Deduplicate systemic failure events by root-attempt identity, not by the changing set of errored children, observer transitions, or a bounded global list that eventually forgets still-polled failures.