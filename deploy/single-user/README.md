# Single-user OBTV on one NVIDIA L4

This deployment is isolated from the existing production stack. It has its own
Compose project name, network, PostgreSQL, Redis, Qdrant, model cache, artifacts,
and host storage paths. It does not use or modify the repository's root
`docker-compose.yml`.

The stack intentionally runs:

- one API service with search embedding models hidden from CUDA
- one GPU worker pinned to GPU 0 with Celery concurrency 1
- one CPU/ingest worker with CUDA hidden
- PostgreSQL, Redis, Qdrant, and the frontend

It intentionally does not run `worker-gpu-2`, BAGEL, ComfyUI/graphics, Flower,
SearxNG, or the Curator XML watcher.

## 1. Host prerequisites

- Docker Engine with Compose v2
- NVIDIA driver and NVIDIA Container Toolkit
- one visible NVIDIA L4 at device 0
- read-only access to Curator WebProxy and HiRes shares

Confirm the GPU before starting:

```bash
nvidia-smi
docker run --rm --gpus '"device=0"' nvidia/cuda:12.8.0-base-ubuntu24.04 nvidia-smi
```

Stop or disable any unrelated process currently consuming L4 memory before
starting this stack.

## 2. Mount Curator shares read-only

Create dedicated mount points:

```bash
sudo mkdir -p \
  /srv/obtv-single/mounts/curator-webproxy \
  /srv/obtv-single/mounts/curator-hires \
  /srv/obtv-single/imports \
  /srv/obtv-single/uploads
```

Use an OS-managed SMB credentials file outside this repository with mode `0600`.
Mount both shares with `ro`. The precise server/share names and domain options
are site-specific; a representative `/etc/fstab` shape is:

```fstab
//CURATOR-SERVER/WEBPROXY /srv/obtv-single/mounts/curator-webproxy cifs ro,credentials=/root/.smb-curator,vers=3.0,nofail,x-systemd.automount 0 0
//CURATOR-SERVER/HIRES    /srv/obtv-single/mounts/curator-hires    cifs ro,credentials=/root/.smb-curator,vers=3.0,nofail,x-systemd.automount 0 0
```

Verify the host can read both mounts before starting OBTV:

```bash
findmnt /srv/obtv-single/mounts/curator-webproxy
findmnt /srv/obtv-single/mounts/curator-hires
test -r /srv/obtv-single/mounts/curator-webproxy
test -r /srv/obtv-single/mounts/curator-hires
```

## 3. Configure the isolated stack

From the repository root:

```bash
cp deploy/single-user/.env.example deploy/single-user/.env
chmod 600 deploy/single-user/.env
```

Edit `.env` and replace every `CHANGE_ME` value. Set Curator's client ID and
the client secret **value** (not the provider's secret identifier). Leave
`OBTV_SINGLE_CURATOR_OAUTH_SCOPE` blank to match the supplied Postman request.

Use an alphanumeric database password so it is safe inside the generated
database URLs. Set `OBTV_SINGLE_CURATOR_MEDIA_ID_QUERY_FIELD` to the canonical
Curator metadata field whose value exactly equals the spreadsheet `Media ID`.
The importer will not use broad or fuzzy name matching.

## 4. Start without touching production

Use the wrapper for every operation. It removes inherited production variables,
forces the `obtv-single` project name, renders the final configuration, and
refuses to continue if the database, volumes, GPU, mounts, service set, or port
could target production:

```bash
bash deploy/single-user/obtv-single.sh up -d --build
```

Check startup and GPU assignment:

```bash
bash deploy/single-user/obtv-single.sh ps
nvidia-smi
```

Open `http://SERVER:5500` (or the configured `OBTV_SINGLE_HTTP_PORT`) and sign in with
the single admin account.

## 5. Import the workbook by Media ID

Copy the workbook into the host `IMPORTS_PATH`. First validate only one row:

```bash
bash deploy/single-user/obtv-single.sh \
  exec api python -m app.commands.import_curator_workbook \
  /imports/Praise_2022-Present_ML_V2.xlsx \
  --media-id HD-P010322 \
  --dry-run
```

If that resolves one exact Curator asset and a readable path, run a ten-row
smoke test:

```bash
bash deploy/single-user/obtv-single.sh \
  exec api python -m app.commands.import_curator_workbook \
  /imports/Praise_2022-Present_ML_V2.xlsx \
  --limit 10
```

Then run all populated IDs:

```bash
bash deploy/single-user/obtv-single.sh \
  exec api python -m app.commands.import_curator_workbook \
  /imports/Praise_2022-Present_ML_V2.xlsx
```

The importer:

- reads only the first worksheet
- requires `Media ID`, `Title`, `TBN_LongSynopsis`, `Host`, and `Guest`
- ignores formatted but empty spreadsheet rows
- requires exact equality on one configured canonical Curator Media ID field
- paginates every Curator result and rejects duplicate or ambiguous matches
- prefers `WebProxyPath`, with configured HiRes fallback
- submits WebProxy assets through OBTV's existing idempotent Curator endpoint
- checkpoints after every ID in `/uploads/import-reports/<workbook>.json`
- skips already queued/imported IDs when rerun

Dry-run rows are deliberately not terminal, so the later real run processes
them normally. Failed and waiting rows remain retryable. To force all successful rows to be
checked again, add `--retry-all`; OBTV's existing path/GUID deduplication prevents
duplicate media records.

## 6. Stop or remove only this instance

Stop:

```bash
bash deploy/single-user/obtv-single.sh down
```

Do not add `--volumes` unless the isolated PostgreSQL, Redis, Qdrant, artifacts,
and model-cache data should be permanently deleted.

Because this file declares the `obtv-single` project and distinct named volumes,
these commands do not address containers or data from the existing production
Compose project.