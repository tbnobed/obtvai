#!/usr/bin/env bash
# Only the secondary server's two DAC interfaces; no storage/management changes.
set -euo pipefail
test "$(hostname)" = obtvai-ingest2
apply() {
  /usr/sbin/ethtool -G enp1s0f0np0 rx 8160 tx 4096
  /usr/sbin/ethtool -C enp1s0f0np0 adaptive-rx off rx-usecs 8
  # Bound bursts into the main server's PCIe-limited receive path.
  # TBF overlimits count deliberate pacing, not discarded packets.
  /usr/sbin/tc qdisc replace dev enp1s0f1np1 root tbf \
    rate 20gbit burst 128kb latency 20ms
}
if [[ "${1:-}" == apply ]]; then
  apply
  exit
fi
install -m 755 "$0" /usr/local/sbin/obtv-dac-throughput
cat > /etc/systemd/system/obtv-dac-throughput.service <<'UNIT'
[Unit]
Description=Qualified receive buffering and main-server DAC pacing
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
apply
