#!/usr/bin/env bash
# Main server only; no daemon-reload (can revoke GPU container device access).
set -euo pipefail
test "$(hostname)" = obtv-llm-2
test -e /sys/class/net/dac1
cat > /etc/NetworkManager/dispatcher.d/90-obtv-dac-rings <<'SCRIPT'
#!/bin/sh
if [ "$1" = dac1 ] && { [ "$2" = up ] || [ "$2" = reapply ]; }; then
    /usr/sbin/ethtool -G dac1 rx 4096 tx 4096
fi
SCRIPT
chmod 755 /etc/NetworkManager/dispatcher.d/90-obtv-dac-rings
ethtool -G dac1 rx 4096 tx 4096
