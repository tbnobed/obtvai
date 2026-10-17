# Direct-link configuration and remaining qualification

2026-10-17: persistent direct addresses were restored on the secondary server.
Default management route and 10-Gb storage paths were not changed. Production
inference relays were deliberately not redirected onto an erroring cable.

| Pair | Main/secondary address | Peer address | MTU |
| --- | --- | --- | --- |
| Main–DGX | main dac0 192.168.101.2 | DGX 192.168.101.1 | 9000 |
| Secondary–DGX | enp1s0f0np0 192.168.100.2 | DGX 192.168.100.1 | 1500 |
| Secondary–main | enp1s0f1np1 192.168.102.3 | main dac1 192.168.102.2 | 9000 |

Deployment scripts:
- `deploy/remote-ingest/configure-dac.sh` installs a netplan overlay for only
  secondary DAC ports, disables DHCP/default-route discovery on those links,
  and installs a boot-time receive/transmit ring adjustment to 4096.
- `deploy/remote-ingest/main-dac-rings.sh` increases main dac1 rings to 4096
  and installs a NetworkManager dispatcher hook without systemd daemon-reload.
- DGX `/etc/netplan/10-dac.yaml` and its active NetworkManager profile have
  enp1s0f0np0 MTU 1500. The other direct link remains at 9000.

## Results, not a clean qualification

Four-stream TCP, 10 measured seconds with two-second warmup:
- Secondary → DGX: 27.76 Gbps; DGX → secondary: 37.71 Gbps at MTU 1500.
- Secondary → main: about 27.15 Gbps; main → secondary: about 27.00 Gbps.
- Prior main ↔ DGX tests: about 27–28 Gbps on a 100-Gb link; main NIC is
  operating at PCIe 3.0 ×4, limiting aggregate capacity.
- Full-size no-fragment pings pass on both configured secondary links.
- DGX vLLM model-list endpoint at 192.168.100.1:8001 responds HTTP 200 over
  secondary DAC. This is connectivity verification, not sustained inference
  qualification or evidence production workers have switched routes.

**DGX cable/port issue remains:** receive CRC and PCS symbol errors increased
during repeated load tests. At MTU 9000 one reverse test collapsed to ~7 Mbps.
Both ends were therefore set to 1500, restoring throughput but not eliminating
CRC errors. Reseat/replace the secondary–DGX DAC and isolate ports if errors
persist. Do not assume firmware flashing or FEC changes are safe fixes:
the Intel side reported FEC Off only.

**Server-to-server receive drops remain:** main RX physical discards and TCP
retransmissions increased under load despite enlarged rings, including a
24-Gbps paced trial. Main sends Ethernet pause frames, but secondary XL710
remained at RX/TX flow control Off after attempted negotiation changes.
No unsupported pause setting was persisted. Investigate NIC firmware/driver
compatibility, PCIe/interrupt capacity and supported flow control before treating
the link as loss-free. Avoid live firmware changes to the dual-port adapter.

Workers, CIFS paths, management SSH and both secondary GPU device mappings
remained available. Temporary benchmark listeners were removed/timeout-bound;
the DGX's pre-existing iperf listener was left alone.
