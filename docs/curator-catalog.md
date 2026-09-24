# Bounded Curator catalog ingest

**This feature is opt-in. No deployment, catalog scan, ingestion, proxy deletion,
or recurring process is performed by adding the code.** API startup only creates
three new tables through the existing bounded-lock schema initializer.

## Rules and limits

- Only `Media`, `Audio`, and `Image` are queried, separately, with
  `assetTypes` and `limit=199`. The known presence query is
  `IngestCompleteDate:*`; no date-range or date-prefix queries are used.
- Compare the explicitly supplied ISO calendar date in `IngestCompleteDate`
  against **2023-01-01 inclusive**. For ISO timestamps, their supplied calendar
  day is used; there is no guessed local timezone or substitution with mtime,
  production date, air date, or library creation date. Missing, ambiguous, and
  invalid dates are `review`, never queued.
- Each full generation first sweeps the date-present results, then the
  unfiltered inventory of those **same three asset types** to find missing
  dates. It never inventories markers or other unsupported types. It restarts
  at offset zero after both sweeps, because offsets can shift as Curator changes.
  Generations are reconciliation passes, **not a claim of a snapshot-complete
  export**. A malformed/missing Id stops that page and records the error without
  advancing; operators must resolve the bad Curator record.
- Exact Curator `Id` is the durable primary key. Page records and cursor commit
  together. Existing XML imports retain their exact Id/path mapping. No guessed
  source filenames, directory-wide SMB scans, or permanent source copies.
- Each run discovers at most `max_pages × 199` records and attempts admission of
  at most `max_assets` assets, with a separate global current inflight ceiling.
  Defaults: **1 page, 10 admissions, 10 inflight, 3 attempts**. Options have
  hard upper bounds; the catalog can persist a large inventory without queuing
  that inventory. Admission is serialized across catalog processes. Unrelated
  watcher/manual producers do not share this admission lock.
- Output watermarks are checked on **actual audio and thumbnail paths**, not
  `/artifacts` (the latter remains the local legacy volume). Default free-space
  floor is 20 GiB plus a conservative 1 GiB reservation per admitted asset.
  This is an admission safeguard, not an exact output-size prediction or SMB
  quota. Add watermarks for local scratch volumes if appropriate.

## Prerequisites (operator actions; do not run without approval)

1. Deploy the API and all media worker images together. `CURATOR_CLIENT_ID`,
   `CURATOR_CLIENT_SECRET`, and the existing `INTERNAL_API_TOKEN` must be
   available to the API container. The existing workbook client's optional
   `CURATOR_API_BASE_URL` and `CURATOR_OAUTH_SCOPE` are reused.
2. Complete the separately documented archive storage preflight. Derived
   `/artifacts/audio` and `/artifacts/thumbnails` child directories must be
   backed by writable CIFS mounts in the API and every media worker. Keep the
   existing local `/artifacts/proxies` untouched; do not migrate it to SMB.
3. Explicitly enable `CURATOR_ARCHIVE_MODE=1` in the API and **every media
   worker**, with consistent `CURATOR_ARCHIVE_ROOTS` (colon-separated absolute
   paths; default `/curator`). Sources must be mounted read-only over CIFS.
   The optional `AUDIO_DIR`/`THUMBNAILS_DIR` must match worker output paths.
   Admission checks `/proc/self/mountinfo` and writes, fsyncs, reads back, and
   removes one tiny probe in each derived-output directory. It never writes to
   a source. A missing share, local fallback, read-only output or failed ACL
   probe blocks apply. Catalog worker entry points repeat this check.
4. Validate real Media/Audio/Image canaries and worker deployment configuration
   before increasing limits. An API-side check cannot prove the mount/env of
   an unrelated downstream worker; the deployment preflight must cover all
   worker containers. Watcher source exclusions remain separately configured.

## Commands

From the API container (after deployment/schema initialization), the safe default
is one bounded, resumable dry-run:

```sh
python -m app.commands.curator_catalog
```

Dry-run persists discovery, dates needing review, errors, checkpoints and run
statistics, and reconciles already-tracked job status. It creates **no media
processing jobs**. Repeating the command resumes the cursor automatically.

After reviewing the results and obtaining ingest approval, an explicit canary:

```sh
python -m app.commands.curator_catalog \
  --apply --confirm QUEUE_BOUNDED_CATALOG \
  --max-pages 1 --max-assets 1 --max-inflight 1 --max-attempts 3 \
  --min-free-gib 20 --reserve-per-asset-mib 1024
```

Add `--storage-path /tmp` (or the actual configured scratch directory) to apply
the same free-space floor there as well. The required audio/thumbnail paths
are always checked, even if omitted from CLI arguments.

Recurring discovery requires **explicit** `--enable-recurring`, optionally
`--interval-seconds 3600` (minimum 60). Without `--apply`, recurring mode remains
dry-run. No service, beat entry, cron job, or startup hook is installed. Stop the
operator process to stop recurrence; bounded progress remains in PostgreSQL.
Preflight/option errors exit nonzero rather than silently continuing.

## Admin integration and recovery

- `GET /api/curator/catalog`: counts by status, checkpoint and latest 20 runs.
  `automatic_discovery:false` means the API installs no automatic scheduler;
  an explicitly launched external recurring CLI process is not tracked as a
  scheduler by this endpoint.
- `GET /api/curator/catalog/assets?status=review&after=&limit=100`: keyset-paged
  review records. Also inspect `retry` and `failed`.
- `POST /api/curator/catalog/run`: same bounded options; `dry_run` defaults true.
  Apply requires `confirm:"QUEUE_BOUNDED_CATALOG"`.
- `POST /api/curator/catalog/assets/{asset_id}/retry`: resets only a terminal
  `failed` record's attempt budget. It **does not queue** anything. Resolve the
  cause first, then explicitly run another bounded apply.

Video first admission reuses the existing durable `/media/curator-import`
contract. Audio/Image and pipeline retries persist job/task IDs and a pending
outbox before broker publication. Broker retries reuse that job/task; worker
per-media locks and terminal-job checks suppress duplicate completed pipelines.
After a publish/commit gap, a pending outbox is recoverable without allocating
another media/job. Do not manually delete outbox records.

Every run reconciles at most 100 tracked rows, rotating by update time. Active
jobs are not retried. Failed pipelines with no active jobs become `retry`,
then `failed` when their bounded attempt budget is spent. Historical errors
before the current pipeline attempt do not poison a successful retry. Explicit
cancel is terminal until an admin reset. `queued` means admitted, **not processed
successfully**; `complete` requires a ready media asset with no active/current
failed jobs. Existing stale-job watchdog/manual job recovery still governs a
worker job that remains indefinitely `running` after a hard worker loss.

## Audio/Image scope

Audio/Image must supply an exact nonempty **file** in `WebProxyPath` beneath the
verified read-only Curator mount. A directory-only path is explicitly blocked;
the importer does not guess an original/audio/image filename or an alternative
UNC mapping. Audio is ffprobe-validated and runs existing extraction,
transcription and indexing without video proxy/scene jobs. Image is decoded,
orientation-corrected, thumbnailed, visually embedded and captioned; readiness
requires real embedding and caption outputs. Animated/multipage images, invalid
audio, missing paths and other unsupported formats fail explicitly.

Source playback/player-format support is separate from semantic indexing.
No new persistent playback copies are created by these Audio/Image paths.

## Tests

The policy tests use only the standard library. Transaction tests also need API
runtime packages plus the test-only `aiosqlite` package; they force an in-memory
SQLite database and never contact Curator, Redis, GPUs or production PostgreSQL:

```sh
PYTHONPATH=services/api python -m unittest discover \
  -s services/api/tests -p 'test_curator_catalog*.py' -v
PYTHONPATH=services/worker python -m unittest discover \
  -s services/worker/tests -p 'test_catalog_media.py' -v
```

These cover inclusive dates, missing/invalid review, exact Id deduplication,
page rollback/resume, reconciliation passes, bad/empty API responses, bounded
retry, broker failure and publish/commit-gap recovery, worker failures,
active-job suppression, CIFS child-mount checks and failed write probes.
Worker tests also validate audio stream gating and use real Pillow decoding to
check still-image thumbnails, source immutability and animated-image rejection.
Live PostgreSQL advisory-lock contention, SMB failure modes and model execution
still require approved integration/canary testing.