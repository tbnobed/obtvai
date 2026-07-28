---
name: Starlette upload spool fills container /tmp
description: Large multipart uploads reset connections when the framework spools to unmounted container /tmp
---

Starlette/FastAPI's multipart parser spools the ENTIRE incoming upload to a
temp file (tempfile default dir) **before** the endpoint handler runs — a
chunked `file.read()` loop in the handler does not prevent this first copy.

**Why:** In Docker, /tmp is the overlay filesystem. Multi-GB uploads fill the
Docker root partition mid-request; the process write fails hard and the
browser sees `ERR_CONNECTION_RESET` (not a clean 413/500). Small files work,
large files "mysteriously" reset — nginx limits and handler code look fine.

**How to apply:** Point the spool at a host-mounted volume early at import
time (`tempfile.tempdir = <uploads-volume>/.tmp` after makedirs), and clear
orphaned spool files at startup. Note uploads are written twice (spool +
destination), so size the volume accordingly.
