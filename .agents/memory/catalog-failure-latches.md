---
name: Catalog failure pause ownership
description: Why worker failures must latch a durable pause regardless of which observer reconciles them.
---

A processing failure must persist an unacknowledged pause independently of the catalog run that first observes it. Dry runs and manual runs must not consume failure notifications intended for the recurring runner.

**Why:** Counting only new status transitions allowed a dry run to notice and mark a failed worker first; the subsequent recurring run then saw zero new failures and could continue admitting assets.

**How to apply:** Check the persistent pause before admission and require explicit acknowledgment to clear it. Test a manual/dry reconciliation followed by a recurring run. Resuming alone is not evidence that a runner is alive; report active discovery only after a real runner heartbeat.