"""Edit the existing private Compose file without exposing its contents.

Run only after draining both GPU workers. CPU routing/storage are unchanged.
"""
import json
import shutil
import socket
import time
from pathlib import Path

assert socket.gethostname() == "obtvai-ingest2", "Secondary host only"
path = Path("/etc/obtv-remote/compose.json")
document = json.loads(path.read_text())
for name in ("gpu0", "gpu1"):
    service = document["services"][name]
    command = service["command"]
    assert isinstance(command, list)
    matches = [i for i, part in enumerate(command) if part.startswith("--queues=")]
    assert len(matches) == 1
    command[matches[0]] = "--queues=gpu-interactive"
    service.setdefault("environment", {})["TRANSLATE_USE_LLM"] = "0"
    service["image"] = "obtv-interactive-worker:verified"
shutil.copy2(path, str(path) + ".before-interactive-" + str(int(time.time())))
temporary = path.with_suffix(".interactive.tmp")
temporary.write_text(json.dumps(document, indent=2) + "\n")
temporary.chmod(path.stat().st_mode & 0o777)
temporary.replace(path)
print("Configured both GPU workers for gpu-interactive; local translation enabled.")
