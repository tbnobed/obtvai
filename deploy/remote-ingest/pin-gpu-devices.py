"""Persist NVIDIA device access across systemd daemon-reload.

Run as root on the remote host before recreating drained GPU workers:
  python3 pin-gpu-devices.py /etc/obtv-remote/compose.json

Does not start/stop containers. Resolves current device minors from GPU UUIDs;
never assumes a GPU's numeric index remained unchanged after a rebuild.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone
import xml.etree.ElementTree as ET


def pin_devices(path: Path):
    config = json.loads(path.read_text())
    report = ET.fromstring(subprocess.check_output(
        ["nvidia-smi", "-q", "-x"], text=True,
    ))
    minors = {
        gpu.findtext("uuid"): gpu.findtext("minor_number")
        for gpu in report.findall("gpu")
    }
    changed = []
    for name in ("gpu0", "gpu1"):
        service = config["services"][name]
        gpu_id = service["deploy"]["resources"]["reservations"]["devices"][0]["device_ids"][0]
        paths = [
            f"/dev/nvidia{minors[gpu_id]}", "/dev/nvidiactl",
            "/dev/nvidia-uvm", "/dev/nvidia-uvm-tools",
        ]
        if not all(Path(p).is_char_device() for p in paths):
            raise RuntimeError(f"Required NVIDIA devices missing for {name}")
        # Keep unrelated device mappings; replace only these NVIDIA paths.
        existing = service.get("devices", [])
        preserved = [d for d in existing if not (
            isinstance(d, str) and d.split(":")[0].startswith("/dev/nvidia")
        )]
        service["devices"] = preserved + [f"{p}:{p}" for p in paths]
        changed.append(name)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.devices-backup-{stamp}")
    shutil.copy2(path, backup)
    path.write_text(json.dumps(config, indent=2) + "\n")
    print("Pinned device access for:", ", ".join(changed))


if __name__ == "__main__":
    pin_devices(Path(sys.argv[1]))
