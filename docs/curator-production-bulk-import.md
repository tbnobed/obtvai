# Curator production bulk import

This runbook imports workbook rows into the existing production OBTV deployment
without using ClipLink or modifying Curator. The command resolves each row by
an **exact** `TBN_MediaIDParent` value, prefers `WebProxyPath`, and only uses
`OriginalPath` after it has been safely confined to the mounted `/media`
source tree.

## Safety rules

- Run the command **inside the production `api` container**. It must see the
  same read-only `/curator` and `/media` mounts as the import endpoint.
- The default mode is a **read-only preflight**. It authenticates to Curator,
  reads metadata, and checks mount availability. It does not call OBTV's
  import endpoint or create a job.
- An execution needs both `--execute` and the exact confirmation phrase
  `--confirm QUEUE_PRODUCTION_IMPORTS`.
- Never paste secrets into the shell, state report, source control, or a
  ticket. `CURATOR_CLIENT_ID`, `CURATOR_CLIENT_SECRET`, and
  `INTERNAL_API_TOKEN` must already be runtime environment secrets in the
  `api` service.
- Do not set or alter `TBN_TransferredToOBTV`, request archive restores, or
  generate proxies as part of this workflow.

## Production contract check

Before preflight, confirm the production deployment includes the batch command
and the `/api/media/curator-import` endpoint. The `api` container must have:

| Requirement | Expected value |
| --- | --- |
| Curator proxy mount | `/curator` (read-only) |
| HiRes mount | `/media` (read-only) |
| Curator credentials | `CURATOR_CLIENT_ID` and `CURATOR_CLIENT_SECRET` |
| OBTV internal authentication | `INTERNAL_API_TOKEN` (needed only for execute) |
| Optional HiRes UNC translation | `CURATOR_HIRES_UNC_PREFIX` matching the external `OriginalPath` prefix |

Keep the Curator Gateway hostname intact for TLS. The production deployment's
existing hostname-preserving DNS override is required when the host's
split-horizon DNS points at an unreachable private address.

Place the workbook at a path readable by the `api` container, for example
`/uploads/imports/praise.xlsx`. Use a state file beneath `/uploads` so it
survives a container restart.

## 1. Run a one-ID read-only preflight

Choose one representative workbook Media ID and run:

```bash
docker compose exec api python -m app.commands.import_curator_workbook \
  /uploads/imports/praise.xlsx \
  --media-id YOUR_MEDIA_ID \
  --state-file /uploads/import-reports/praise-production.json
```

Review the JSON state report before proceeding. A usable item reports
`dry-run-ready` plus:

- `curator_asset_id` — the exact Curator GUID,
- `source_type` — `web-proxy`, `hires-fallback`, or `hires-only`,
- `mapped_source_path` — a path below the expected mount.

`failed` rows are not eligible for execution. Common safe failures are no
exact Media ID, multiple exact matches, an unavailable proxy without a usable
HiRes fallback, or a path outside the allowed mounts. Correct the mount or
metadata issue; do not substitute a filename or fuzzy search.

## 2. Execute one validated ID

Only after the one-ID preflight is reviewed and approved, queue that same row:

```bash
docker compose exec api python -m app.commands.import_curator_workbook \
  /uploads/imports/praise.xlsx \
  --media-id YOUR_MEDIA_ID \
  --state-file /uploads/import-reports/praise-production.json \
  --execute --confirm QUEUE_PRODUCTION_IMPORTS
```

The result should be `queued`, `existing`, or `imported`. Those are terminal
and are skipped on later runs. Confirm the asset appears in OBTV and its
processing job is visible before expanding the batch.

## 3. Run a ten-ID smoke gate

Create a clean state file for the smoke run. First preflight ten workbook rows:

```bash
docker compose exec api python -m app.commands.import_curator_workbook \
  /uploads/imports/praise.xlsx \
  --limit 10 \
  --state-file /uploads/import-reports/praise-smoke.json
```

Review every row and confirm the expected source type. Then, and only then,
repeat the command with:

```text
--execute --confirm QUEUE_PRODUCTION_IMPORTS
```

Check API logs, the jobs interface, and the imported media for each queued
row. Stop here if any source path, GUID, duplicate behavior, or processing
stage is unexpected.

## 4. Full workbook preflight and execution

Use a new persistent report for the full workbook:

```bash
# Read-only preflight for every row
docker compose exec api python -m app.commands.import_curator_workbook \
  /uploads/imports/praise.xlsx \
  --state-file /uploads/import-reports/praise-full.json

# Execute only after the preflight report is approved
docker compose exec api python -m app.commands.import_curator_workbook \
  /uploads/imports/praise.xlsx \
  --state-file /uploads/import-reports/praise-full.json \
  --execute --confirm QUEUE_PRODUCTION_IMPORTS
```

The command retries only transport errors, with bounded backoff. Use
`--max-attempts 1` through `--max-attempts 5` when a different retry budget is
needed. It never guesses a source path or changes Curator metadata.

## Monitoring and interruption recovery

Monitor API and worker activity while the execution runs:

```bash
docker compose logs -f api worker-gpu worker-gpu-2 worker-cpu
```

The state file is atomically written before and after each row. If the command
is interrupted, rerun the same command with the same workbook and state file:

- `queued`, `existing`, and `imported` rows are skipped automatically.
- `dry-run-ready`, `waiting`, and `failed` rows are rechecked.
- Add `--retry-all` only when intentionally rechecking terminal rows; the
  OBTV Curator import endpoint is idempotent by Curator GUID.

Do not reuse a state file for a different workbook; the command rejects a
workbook-name mismatch to prevent accidental cross-batch skips.

## Safe stop and rollback boundaries

To stop new submissions, interrupt the command. It will finish no new rows
after the current request returns. To prevent queued media from beginning
processing, stop the relevant worker services after confirming the queue
impact with the operations team.

There is no automatic rollback: a queued/imported OBTV asset may already have
downstream jobs and generated artifacts. Do not delete database records,
media files, or Curator metadata as a generic rollback. Any reversal must be
an explicitly approved, asset-by-asset OBTV operation with its own backup and
audit plan.