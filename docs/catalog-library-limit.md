# Benchmark ingestion stop

The selected benchmark target is **10,000 total ready library assets**, not
10,000 catalog completions or videos. `CURATOR_CATALOG_READY_LIMIT=10000` must
be set on both the API and catalog runner.

Catalog admission holds the existing shared advisory lock and checks the budget
before each import. Count ready media once, plus distinct non-ready media already
pending/processing or with active jobs. Jobs on already-ready media do not reserve
another asset. Existing reserved publication retries do not consume a second slot.
When all remaining slots are reserved, admission waits rather than terminating work.

At the target, a separate durable checkpoint latches the stop. Model auto-recovery,
ordinary Resume, and a later decrease in ready count cannot bypass the configured
limit. Raising/removing the configured limit is a separate operator action; an
existing runner pause still requires acknowledgment. No worker is stopped.

This controls automatic and manual **catalog** batches, not independent user
uploads/import endpoints. Do not add new assets through those endpoints while
establishing the benchmark dataset. Already-running jobs and external imports are
never cancelled or deleted merely to force an exact count.

The second server's translation/GPU role remains a proposed configuration; setting
the benchmark stop does not change its current queues, storage permissions or GPUs.
