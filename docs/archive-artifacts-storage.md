# Archive artifacts: opt-in storage

The existing `/artifacts` root stays on the **local** `artifacts_data` volume,
even with `archive-artifacts.compose.yml`. The overlay binds **only**
`audio`, `thumbnails`, `reels`, `renders`, `dubs`, `voices`, and `graphics`
below `/artifacts` on `api`, `worker-gpu`, `worker-gpu-2`, `worker-cpu`, and
`worker-graphics` to the dedicated `\\10.81.100.220\ipv\OBTV-AI` output
folder (host: `/mnt/curator-ipv/OBTV-AI`). These are the derived output
directories used by the API and workers. `/artifacts/proxies` and
`curator_proxy_index.json` stay **local**; existing legacy `proxy_path` DB
references remain readable, and local/non-archive upload behavior is
unchanged. Existing proxy files are **not** copied to SMB, deleted, or claimed
to be zero: a separate audited cleanup decision is deferred.

`postgres`, `qdrant`, Redis, model caches, source media and the local legacy
proxy volume are unchanged. The watcher does **not** mount or scan the output
folder. `CURATOR_ARCHIVE_MODE=0` by default; `CURATOR_ARCHIVE_ROOTS=/curator`
selects which container paths use source-backed playback and skip new retained
proxies when mode is explicitly enabled. These are *container* paths; the
archive `IngestCompleteDate` cutoff is a separate catalog decision. All new
archive playback must use source-backed playback; no `/artifacts/proxies/*.mp4`
should be generated for archive assets.

## Operator-only procedure (not run by application deploy)

1. On the production Docker host, verify the existing SMB mount is active and
   the dedicated directory exists. Keep this directory **outside** `MEDIA_PATH`,
   `MEDIA_PATH_2`, `CURATOR_PROXY_PATH`, and `CURATOR_INBOX_PATH`; never add it to
   watcher `MEDIA_ROOTS` or turn it into an upload/source tree. Ensure the CIFS
   mount survives reboot. Host SSH user has no write access; host root and the
   root-running API/worker containers must have read/write access. If the mount
   isn't active, **stop**: bind mounts on unmounted paths can fill local disk.
   The already-performed uid-0 SMB test verified disposable root-level
   write/read/rename/delete, but the seven child directories still require
   explicit creation and validation. **Only after confirming SMB is mounted**,
   prepare these exact subdirectories on the host:

   ```sh
   sudo mkdir -p -- /mnt/curator-ipv/OBTV-AI/{audio,thumbnails,reels,renders,dubs,voices,graphics}
   ```

   No script implicitly creates arbitrary share directories. The preflight
   probes write/read/rename/delete in *each* child directory and refuses
   missing, symlinked, non-CIFS or unwritable directories.
2. From the repository root on that host, with the normal production `.env`
   (do not source or display secrets):

   ```sh
   sudo ./scripts/archive-artifacts-preflight.sh
   sudo ./scripts/archive-artifacts-migrate.sh
   ```

   Requires `docker compose`, `jq`, `findmnt`, `realpath`, and `rsync`. The
   preflight rejects non-CIFS paths, bad ownership/write access and overlaps
   with configured watcher roots. It writes/reads/removes only one probe file.
   The copy command defaults to **dry-run** and neither deletes nor overwrites
   destination files. It copies **only** the seven listed subdirectories:
   `proxies/` (including `proxies/*.mp4`) and all other root files/directories
   are explicitly omitted. Both commands resolve the base Compose project to
   locate the existing `artifacts_data` volume, not a guessed Docker path.
   If sudo does not retain the intended project environment, run from the
   production project directory with the same Compose project name/.env; do
   not proceed if the reported volume name/source is unexpected.
3. Schedule a maintenance window and stop writers before copying: `api`,
   `worker-gpu`, `worker-gpu-2`, `worker-cpu`, `worker-graphics`. Do not stop
   databases or remove volumes. The apply command refuses running writers.
   Review dry-run output and source/target paths, then:

   ```sh
   sudo ./scripts/archive-artifacts-migrate.sh --apply
   ```

   It copies missing files only in the seven output subdirectories, refuses
   conflicting destination contents, and compares them by content/symlink
   target afterward. A subdirectory absent from the old volume is skipped
   (its empty SMB destination is still required). CIFS may not support POSIX
   chown/chmod: bytes, layout, symlinks and mtimes are transferred. Any error
   or verification failure means **do not enable** the overlay. Never delete
   or move the source volume or local proxies as part of this procedure.
4. Before cutover, explicitly set `CURATOR_ARCHIVE_MODE=1` for the API and
   media workers and confirm `CURATOR_ARCHIVE_ROOTS` includes the appropriate
   source container path (default `/curator`). Keep
   `WATCHER_EXCLUDE_ROOTS=/artifacts` (colon-separated container paths; watcher
   always excludes `/artifacts` even if the variable is unset). Never place
   the OBTV-AI output share under the watched `/media` or `/media2` trees.
   Keep the watcher out of this storage-only rollout. Only after successful
   verification, opt in when starting the five writers:

   ```sh
   docker compose -f docker-compose.yml -f archive-artifacts.compose.yml config --format json | jq -r '.services.api.volumes[] | select(.target == "/artifacts" or .target == "/artifacts/audio" or .target == "/artifacts/thumbnails") | [.target,.source] | @tsv'
   docker compose -f docker-compose.yml -f archive-artifacts.compose.yml up -d --no-deps api worker-gpu worker-gpu-2 worker-cpu worker-graphics
   ```

   Check the container mounts (`/artifacts` must remain the named volume;
   `/artifacts/audio` and `/artifacts/thumbnails` must be CIFS-backed bind
   mounts) and application writes before accepting the change. Catalog
   preflight must test **both `/artifacts/audio` and `/artifacts/thumbnails`**
   as CIFS mounts, **not `/artifacts`**. Continue using both `-f` arguments for subsequent operations on
   these services. Do **not** include `watcher` in this storage-only rollout:
   its startup behavior can rescan media roots. Start it separately only with
   an approved watcher rollout plan.

### Rollback

Stop the five writers. **Do not** switch derived-output directories back to
the old local volume without first staging and verifying any files created on
SMB back to it under the same collision safeguards; local proxy files remain
unchanged, but local derived-output folders are stale after new SMB writes. If
the SMB mount disappears, stop writers; never let Docker start bind mounts
against a missing mount. No script here purges either storage location.

Offline contract check: `bash scripts/test-archive-artifacts.sh`.