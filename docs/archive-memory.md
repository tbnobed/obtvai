# Indexed archive memory

Production QA keeps global transcript ANN and indexed substring matching, then
interleaves a bounded set of additional transcript passages selected through
asset-summary vectors. Summary text is a routing aid, never a fabricated quote
or timestamp. Deleted and edited summaries are rejected during SQL hydration.
The existing configured text encoder is reused; its model identity determines
a separate collection name. No transcript or scene collection is recreated.

Library overview and literal mention counts have durable PostgreSQL caches,
versioned by transactionally committed data changes and expiring after five
minutes. Statement-level triggers catch API writes and raw worker SQL alike.
Cache row locks are released before an LLM call. Current roles share the library;
single-asset counts have separate keys. Future per-asset ACLs MUST add permission
revision/scope to these keys and every retrieval query.

Strictly phrased questions such as `How many assets mention "Mary Jane"?` return
exact distinct-asset transcript substring counts without generation or vector
search. Zero is a valid result. A single quoted literal plus optional trailing
punctuation is required. Unquoted, Boolean, date/person-qualified, and semantic
count questions return an explicit unsupported-count explanation, never an LLM
guess. Cache keys preserve the original Unicode term: Python casefold is not
PostgreSQL ILIKE equivalence. Optional cache read/write failures are logged and
isolated from the conversation transaction; a valid measured result still returns.
Ordinary
questions no longer run four ad-hoc whole-library mention/person counts.

## Explicit rollout (not an API-startup migration)

Build the changed API source first. Retain the existing archive overlay.
No workers need rebuilding: database triggers populate the durable summary
outbox after analysis commits, including future image/topic edits and deletions.

```sh
docker compose -f docker-compose.yml -f archive-artifacts.compose.yml build api
docker compose -f docker-compose.yml -f archive-artifacts.compose.yml run --rm --no-deps \
  -e CUDA_VISIBLE_DEVICES= --entrypoint python api -m app.commands.archive_memory migrate
```

Migration adds only small auxiliary tables, functions, and triggers, plus
`pg_trgm` and concurrent GIN indexes on transcript text and people names.
It does NOT rewrite transcript rows or alter hot-table columns at boot.
DDL has a two-second lock timeout; retry a failed migration rather than disabling
the guard. Concurrent index builds can take time/I/O on a large archive; schedule
off-peak. A rerun detects/rebuilds an invalid interrupted index concurrently.
The database operator needs extension/index/trigger creation privileges.

Start with a bounded ten-asset canary, not a 200K rebuild:

```sh
docker compose -f docker-compose.yml -f archive-artifacts.compose.yml run --rm --no-deps \
  -e CUDA_VISIBLE_DEVICES= --entrypoint python api -m app.commands.archive_memory backfill --limit 10
docker compose -f docker-compose.yml -f archive-artifacts.compose.yml run --rm --no-deps \
  -e CUDA_VISIBLE_DEVICES= --entrypoint python api -m app.commands.archive_memory drain --limit 10
docker compose -f docker-compose.yml -f archive-artifacts.compose.yml run --rm --no-deps \
  --entrypoint python api -m app.commands.archive_memory status
```

Backfill returns `next_after`; explicitly pass `--after ID` to enqueue the next
page, at most 100 per command. Repeating a page is idempotent. It does not rerun
transcription or analysis. Assets without summaries/topics do not get invented
embeddings. Failures leave pending work in the outbox.

After verifying the canary, enable automatic incremental processing:

```sh
docker compose -f docker-compose.yml -f archive-artifacts.compose.yml \
  -f archive-memory.compose.yml --profile archive-memory up -d --no-deps api archive-memory
```

The opt-in `archive-memory` service uses the just-built API image, the same
`EMBEDDINGS_MODEL`, shared model cache, CPU only, ten dirty assets per minute.
Set `COMPOSE_PROJECT_NAME` if your API image is not named `obtv-ai-api`.
No new GPU model or remote LLM setting is introduced. Rebuilding API later
requires recreating this service too to pick up maintenance-code changes.

## Verification and limits

- Run `python -m unittest discover -s tests -p 'test_archive_memory*.py' -v`.
  PostgreSQL integration tests are opt-in on a disposable database whose name
  ends `_archive_memory_test`; set `ARCHIVE_MEMORY_TEST_DATABASE_URL`. Never use
  production. They validate actual trigger rollback/delete behavior.
- Time the same overview question twice; inspect `status` cache rows/versions.
  Insert/edit/delete in a disposable DB, then verify counts/cache revision change.
- Inspect `EXPLAIN (ANALYZE, BUFFERS)` on the real substring-count query before
  and after indexes, using representative rare/common names. PostgreSQL may
  rationally choose a sequential scan for very common terms or small tables.
  The operator command `python -m app.commands.archive_memory benchmark
  --term "Mary Jane"` emits the actual plan plus two count-call timings, with a
  15-second query timeout. Run through the same API one-off container command
  above. It does not invent baseline speedups or invoke the LLM.
- Verify direct transcript evidence still works when the new collection is
  empty/unavailable. Check scoped questions cannot hydrate other assets.
- The first overview after invalidation still aggregates current SQL facts.
  This is a cache, not approximate incremental topic counters. Heavy sustained
  ingestion may invalidate it frequently. No question/result-answer cache is
  added, and no model-training behavior changes in this component.
- Missing migration logs an explicit warning and uses uncached overviews.
  A missing/unavailable summary collection logs a warning and uses direct
  transcript/keyword evidence. Never silently recreate an incompatible index.
- Regular DELETE mutations enqueue cleanup. Administrative TRUNCATE invalidates
  cache and stale vectors cannot hydrate, but requires a deliberate collection
  cleanup/rebuild if physical vector removal is needed.