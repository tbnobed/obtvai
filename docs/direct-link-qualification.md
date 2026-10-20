# Direct-link configuration and remaining qualification

## October 20 retest

All three pairs passed 20 full-MTU, do-not-fragment pings with zero loss.
Explicit source bindings and route lookups on both ends confirmed direct DAC
routing, not the management or storage networks.

Four parallel TCP streams, 15 measured seconds plus two-second warmup:

| Direction | Receiver Gbps | Sender retransmissions |
| --- | ---: | ---: |
| Main → Spark | 26.94 | 2 |
| Spark → main | 28.38 | 0 |
| Secondary → Spark | 37.65 | 1,686 |
| Spark → secondary | 37.70 | 4,344 |
| Secondary → main | 27.09 | 44,708 |
| Main → secondary | 27.01 | 104 |

Before/after hardware-counter deltas:
- No new CRC or symbol errors on the tested ports. The prior secondary–Spark
  physical-error condition was not reproduced in this short test.
- Main dac1 RX physical discards increased 50,187; the matching priority-zero
  discard counter increased by the same amount (not an additional 50,187).
- Secondary's Spark-facing NIC RX missed errors increased 2,331.
- Spark error/drop counters showed no increase.

Conclusion: connectivity and throughput pass; saturation-loss qualification
does not. Resolve receive-side drops or qualify a paced operating limit before
calling the secondary fully ready for the new worker role.

Secondary storage NIC remains linked at 10 Gb/s and both checked CIFS-server
routes use that interface. Both worker GPU containers can query their intended
GPU. Existing three ingestion containers remain running; no queue/role changes
were made. Spark model containers remain stopped for previously authorized
maintenance, so model-serving readiness was not established by these tests.
Temporary port-5209 listeners were stopped; no network configuration changed.

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
