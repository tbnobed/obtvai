"""Read the watcher's local heartbeat without touching potentially blocked SMB."""
import json
import math
import os
import sys
import time


def check(path: str, max_age: float = 180, now: float | None = None) -> bool:
    try:
        with open(path, encoding="utf-8") as stream:
            state = json.load(stream)
        age = (time.time() if now is None else now) - float(state["updated_at"])
        return state["healthy"] is True and math.isfinite(age) and 0 <= age <= max_age
    except (OSError, ValueError, KeyError, TypeError):
        return False


if __name__ == "__main__":
    sys.exit(0 if check(
        os.getenv("WATCHER_HEALTH_FILE", "/tmp/watcher-health.json"),
        float(os.getenv("WATCHER_HEALTH_MAX_AGE", "180")),
    ) else 1)