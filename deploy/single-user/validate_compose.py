"""Validate that rendered Compose configuration cannot target production."""

from __future__ import annotations

import json
import sys
from urllib.parse import urlparse


EXPECTED_SERVICES = {
    "api",
    "frontend",
    "postgres",
    "qdrant",
    "redis",
    "worker-cpu",
    "worker-gpu",
}
EXPECTED_VOLUMES = {
    "artifacts_data",
    "models_cache",
    "postgres_data",
    "qdrant_data",
    "redis_data",
}


def fail(message: str) -> None:
    print(f"single-user preflight failed: {message}", file=sys.stderr)
    raise SystemExit(2)


def main() -> None:
    try:
        config = json.load(sys.stdin)
    except (ValueError, OSError) as exc:
        fail(f"could not parse rendered Compose config: {exc}")

    if config.get("name") != "obtv-single":
        fail("Compose project name is not exactly 'obtv-single'")
    services = config.get("services")
    if not isinstance(services, dict) or set(services) != EXPECTED_SERVICES:
        fail("rendered service set does not match the isolated deployment")

    api_environment = services["api"].get("environment") or {}
    database_url = api_environment.get("DATABASE_URL", "")
    parsed = urlparse(database_url)
    if parsed.hostname != "postgres" or parsed.path != "/obtv":
        fail("API database URL does not target the isolated 'postgres/obtv' service")

    for name in EXPECTED_VOLUMES:
        volume = (config.get("volumes") or {}).get(name) or {}
        if volume.get("name") != f"obtv-single_{name}":
            fail(f"volume {name!r} is not namespaced to obtv-single")

    ports = services["frontend"].get("ports") or []
    published = {str(port.get("published")) for port in ports if isinstance(port, dict)}
    if "5000" in published:
        fail("host port 5000 is reserved for the existing production deployment")

    required_read_only = {
        "api": {"/media", "/curator", "/imports"},
        "worker-gpu": {"/media", "/curator", "/uploads"},
        "worker-cpu": {"/media", "/curator"},
    }
    for service_name, targets in required_read_only.items():
        volumes = services[service_name].get("volumes") or []
        mounts = {
            mount.get("target"): mount
            for mount in volumes
            if isinstance(mount, dict)
        }
        for target in targets:
            if target not in mounts or not mounts[target].get("read_only"):
                fail(f"{service_name} mount {target} is not read-only")

    gpu_devices = (
        services["worker-gpu"]
        .get("deploy", {})
        .get("resources", {})
        .get("reservations", {})
        .get("devices", [])
    )
    if len(gpu_devices) != 1 or gpu_devices[0].get("device_ids") != ["0"]:
        fail("GPU worker is not pinned exclusively to device 0")
    if (
        services["api"].get("environment", {}).get("CUDA_VISIBLE_DEVICES") != ""
        or services["worker-cpu"].get("environment", {}).get("CUDA_VISIBLE_DEVICES") != ""
    ):
        fail("API and CPU worker must have CUDA hidden")

    print("single-user Compose preflight passed")


if __name__ == "__main__":
    main()