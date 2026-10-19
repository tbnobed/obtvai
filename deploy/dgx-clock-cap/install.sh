#!/usr/bin/env bash
set -euo pipefail
test "$(id -u)" = 0
test "$(hostname)" = spark-174a
cd "$(dirname "$0")"
stamp=$(date +%Y%m%d%H%M%S)
for path in /usr/local/sbin/obtv-gpu-clock-cap \
    /etc/systemd/system/obtv-gpu-clock-cap.service \
    /etc/systemd/system/docker.service.d/20-obtv-gpu-clock-cap.conf; do
  if test -e "$path"; then cp -a "$path" "$path.before-$stamp"; fi
done
install -m 755 apply-clock-cap.sh /usr/local/sbin/obtv-gpu-clock-cap
install -m 644 obtv-gpu-clock-cap.service /etc/systemd/system/obtv-gpu-clock-cap.service
install -d -m 755 /etc/systemd/system/docker.service.d
cat > /etc/systemd/system/docker.service.d/20-obtv-gpu-clock-cap.conf <<'CONF'
[Unit]
Requires=obtv-gpu-clock-cap.service
After=obtv-gpu-clock-cap.service
CONF
systemd-analyze verify /etc/systemd/system/obtv-gpu-clock-cap.service
# Never daemon-reload here: existing NVIDIA-runtime containers may lose device
# access. systemd reads the enabled unit and Docker dependency at the next boot.
systemctl enable --no-reload obtv-gpu-clock-cap.service
timeout 95 /usr/local/sbin/obtv-gpu-clock-cap
systemctl is-enabled obtv-gpu-clock-cap.service
