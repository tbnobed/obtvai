#!/usr/bin/env bash
# Diagnostic containment, not a fix for the underlying shutdown cause.
set -euo pipefail
for attempt in $(seq 1 30); do
  if timeout 10 /usr/bin/nvidia-smi -i 0 --lock-gpu-clocks=300,2100; then
    echo "DGX GPU clock range locked to 300–2100 MHz."
    exit 0
  fi
  echo "GPU clock lock attempt $attempt failed; waiting for the driver." >&2
  sleep 2
done
echo "GPU clock cap could not be applied; Docker startup must remain blocked." >&2
exit 1
