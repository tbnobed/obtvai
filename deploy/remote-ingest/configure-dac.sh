#!/usr/bin/env bash
# Run as root on the rebuilt ingestion server only. Leaves management/storage
# configuration untouched; direct links have no gateway or DNS.
set -euo pipefail
test "$(hostname)" = obtvai-ingest2
for nic in enp1s0f0np0 enp1s0f1np1; do
  test "$(cat /sys/class/net/"$nic"/carrier)" = 1
done
file=/etc/netplan/70-obtv-dac.yaml
if test -e "$file"; then cp -a "$file" "$file.bak.$(date +%s)"; fi
cat > "$file" <<'YAML'
network:
  version: 2
  ethernets:
    enp1s0f0np0:
      dhcp4: false
      dhcp6: false
      accept-ra: false
      optional: true
      # Match the DGX peer. Jumbo traffic failed qualification on this cable.
      mtu: 1500
      addresses: [192.168.100.2/24]
    enp1s0f1np1:
      dhcp4: false
      dhcp6: false
      accept-ra: false
      optional: true
      mtu: 9000
      addresses: [192.168.102.3/24]
YAML
chmod 600 "$file"
netplan generate
# Do not use broad netplan apply: preserve active SSH, CIFS and worker relays.
networkctl reload
networkctl reconfigure enp1s0f0np0 enp1s0f1np1
cat > /etc/systemd/system/obtv-dac-rings.service <<'UNIT'
[Unit]
Description=Receive buffering for ingestion server direct links
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
ExecStart=/usr/sbin/ethtool -G enp1s0f0np0 rx 4096 tx 4096
ExecStart=/usr/sbin/ethtool -G enp1s0f1np1 rx 4096 tx 4096
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now obtv-dac-rings.service
ip route get 192.168.100.1
ip route get 192.168.102.2
ping -c 3 -W 2 -M do -s 1472 -I 192.168.100.2 192.168.100.1
ping -c 3 -W 2 -M do -s 8972 -I 192.168.102.3 192.168.102.2
