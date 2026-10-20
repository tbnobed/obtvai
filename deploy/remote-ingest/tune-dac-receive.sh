#!/usr/bin/env bash
# Only the secondary server's two DAC interfaces; no storage/management changes.
set -euo pipefail
test "$(hostname)" = obtvai-ingest2
apply() {
  for nic in enp1s0f0np0 enp1s0f1np1; do
    # i40e's -A autoneg argument does not change link autonegotiation.
    # Both direct Mellanox peers use fixed-speed, non-autoneg links.
    /usr/sbin/ethtool -s "$nic" speed 40000 duplex full autoneg off
    /usr/sbin/ethtool -A "$nic" rx on tx on
    ready=0
    for attempt in $(seq 1 30); do
      pause=$(/usr/sbin/ethtool -a "$nic")
      if [[ "$(cat /sys/class/net/"$nic"/carrier)" = 1 ]] &&
         grep -Eq '^RX:[[:space:]]*on$' <<<"$pause" &&
         grep -Eq '^TX:[[:space:]]*on$' <<<"$pause"; then
        ready=1
        break
      fi
      sleep 1
    done
    [[ "$ready" = 1 ]] || { echo "Flow control did not settle on $nic" >&2; return 1; }
  done
  /usr/sbin/ethtool -G enp1s0f0np0 rx 8160 tx 4096
  # The successful concurrent tests used the driver's adaptive RX defaults
  # restored during link/DCB renegotiation, not the earlier 8-us trial.
  /usr/sbin/ethtool -C enp1s0f0np0 adaptive-rx on rx-usecs 50
  # Migrate only our earlier 20-Gbit TBF containment, never arbitrary policies.
  root_qdisc=$(/usr/sbin/tc qdisc show dev enp1s0f1np1 | grep ' root ')
  if grep -Eq '^qdisc tbf .*rate 20Gbit ' <<<"$root_qdisc"; then
    /usr/sbin/tc qdisc replace dev enp1s0f1np1 root mq
  elif ! grep -q '^qdisc mq ' <<<"$root_qdisc"; then
    echo "Unexpected DAC root qdisc; refusing to replace: $root_qdisc" >&2
    return 1
  fi
}
if [[ "${1:-}" == apply ]]; then
  apply
  exit
fi
install -m 755 "$0" /usr/local/sbin/obtv-dac-throughput
cat > /etc/systemd/system/obtv-dac-throughput.service <<'UNIT'
[Unit]
Description=DAC flow control and receive buffering
Wants=network-online.target obtv-dac-rings.service
After=network-online.target obtv-dac-rings.service
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/obtv-dac-throughput apply
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
UNIT
systemd-analyze verify /etc/systemd/system/obtv-dac-throughput.service
# Avoid disturbing NVIDIA container device access with daemon-reload.
systemctl enable --no-reload obtv-dac-throughput.service
if [[ "${1:-}" != --install-only ]]; then
  apply
fi
