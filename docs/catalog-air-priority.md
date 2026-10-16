# Original-air-date ingestion priority

The recurring catalog runner reads `CURATOR_CATALOG_PRIORITY_AIR_YEAR`.
The remote-ingest override sets it to 2026. Matching assets rank before the
existing media-type rotation and FIFO age. This changes ordering only:
eligibility still uses its existing ingest-date cutoff, missing dates still
require review, attempts/concurrency remain bounded, and running jobs are
untouched. Unknown original-air dates never inherit the ingest date.

Discovery requests Curator's verified `TBN_OriginalAirDate` field and records
an internal normalized year only for a single valid ISO original-air date.
Every ordinary discovery refresh recalculates this annotation.

Existing snapshots need enrichment before they can be prioritized. Run inside
the updated catalog-runner image:

```sh
python -m app.commands.catalog_air_priority --max-pages 2000
```

This finite metadata-only sweep uses the Gateway's supported field-existence
query and the separate `original-air-discovery` checkpoint. It resumes after
interruption, shares the normal admission advisory lock only during database
writes, and preserves active jobs, attempt counts, and existing queue ages.
It does not enqueue jobs or reset normal discovery cursors. New matching rows
are still subject to normal eligibility. A completed sweep stops; ordinary
discovery handles subsequent metadata changes.

Operational deployment: the current main runner uses the derivative image
`obtv-api-air-priority:2026`, built from the deployed API image with the changed
catalog modules. The main operator's remote-ingest override selects that image.
Rebuild the API image from current source before returning to the default
catalog image. No GPU worker image change is required.

Verification covers missing, ambiguous, invalid, older and boundary dates;
live query ordering must show matching-year eligible rows before other years.
Do not clear an infrastructure pause merely to demonstrate priority: first
verify actual model generation, then reconcile and clear only the recovered
failure under the existing admission lock.
