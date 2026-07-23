---
name: Postgres startup DDL locks
description: Why idempotent ALTER TABLE migrations at boot deadlock against busy workers, and the catalog-check pattern that avoids it.
---

**Rule:** Never re-run `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` (or `ALTER COLUMN ... DROP NOT NULL`) lists unconditionally at startup. `IF NOT EXISTS` acquires the ACCESS EXCLUSIVE lock *before* checking existence, so every boot takes exclusive locks on every migrated table.

**Why:** On a busy library, workers hold long locks on hot tables (media_assets, transcript_segments). The API's startup migration retried 5× against `lock_timeout=5s` and the container went unhealthy — deploy failed with "dependency api failed to start".

**How to apply:** Query `information_schema.columns` for the schema once, build a `(table, column)` set, and only execute ALTERs for columns actually missing (and only DROP NOT NULL where `is_nullable='NO'`). DO-block migrations that check information_schema before ALTERing are already safe.
