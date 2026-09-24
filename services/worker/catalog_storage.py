"""Fail-closed archive admission, inspecting actual child mounts, not /artifacts."""
import os
import re
import tempfile
from pathlib import Path


def mount_for(path, mountinfo):
    target = Path(path).resolve()
    matches = []
    for line in mountinfo.splitlines():
        left, separator, right = line.partition(" - ")
        if not separator:
            continue
        fields, filesystem = left.split(), right.split()
        if len(fields) < 6 or len(filesystem) < 3:
            continue
        mountpoint = Path(re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), fields[4]))
        if target == mountpoint or mountpoint in target.parents:
            matches.append((len(mountpoint.parts), filesystem[0], fields[5].split(",")))
    if not matches:
        raise RuntimeError(f"Cannot establish filesystem backing {path}")
    return max(matches, key=lambda item: item[0])[1:]


def require_archive_storage():
    if os.getenv("CURATOR_ARCHIVE_MODE", "").lower() not in ("1", "true", "yes"):
        raise RuntimeError("Catalog apply requires CURATOR_ARCHIVE_MODE=1 in API and every media worker")
    info = Path("/proc/self/mountinfo").read_text()
    sources = [Path(p).resolve() for p in os.getenv("CURATOR_ARCHIVE_ROOTS", "/curator").split(os.pathsep) if p]
    if not sources:
        raise RuntimeError("CURATOR_ARCHIVE_ROOTS is empty")
    for source in sources:
        fs, options = mount_for(source, info)
        if not source.is_dir() or fs not in ("cifs", "smb3") or "ro" not in options:
            raise RuntimeError(f"Archive source must be an available read-only CIFS mount: {source}")
    paths = [os.getenv("AUDIO_DIR", "/artifacts/audio"), os.getenv("THUMBNAILS_DIR", "/artifacts/thumbnails")]
    for value in paths:
        path = Path(value).resolve()
        fs, options = mount_for(path, info)
        if not path.is_dir() or fs not in ("cifs", "smb3") or "rw" not in options:
            raise RuntimeError(f"Derived output must be a writable CIFS mount: {path}")
        if any(path == source or source in path.parents or path in source.parents for source in sources):
            raise RuntimeError("Derived outputs must not overlap archive source roots")
        # A filesystem/mode check alone does not validate SMB ACLs or liveness.
        # Never test writes in a source tree. Remove this small probe in finally.
        with tempfile.NamedTemporaryFile(prefix=".obtv-catalog-probe-", dir=path) as probe:
            payload = b"obtv-catalog-storage-check\n"
            probe.write(payload)
            probe.flush()
            os.fsync(probe.fileno())
            probe.seek(0)
            if probe.read() != payload:
                raise RuntimeError(f"Derived output write/read verification failed: {path}")
    return paths