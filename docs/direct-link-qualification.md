# Direct-link configuration and remaining qualification

## October 20 follow-up: port drops identified and flow control qualified

This section supersedes the incomplete mitigation and qualification statements
below, which are retained as investigation history.

The earlier "hardware drop counters flat" conclusion was too broad: the Intel
driver's `port.rx_discards` counter was not included in that check. It increased
by 287,201 on the Spark-facing port in a new concurrent-receive test while
queue-level `rx_missed_errors` and softnet drop counters stayed flat.
Sender qdisc drop counts also stayed zero. This establishes real port-level
loss, not only spurious TCP retransmission.

Both Intel ports initially had RX/TX pause off. Fixed-speed link configuration
with `ethtool -s ... speed 40000 duplex full autoneg off`, followed by
`ethtool -A ... rx on tx on`, enabled pause on both. The main-facing port
previously retained autoneg on: -A does not change link autonegotiation.
Immediate pause readback can be stale until renegotiation completes; verify
carrier and settled readback. A firmware-LLDP disable trial was reverted;
default firmware LLDP remains enabled and no NIC firmware was changed.

Final retained settings:
- Both secondary DACs: fixed 40-Gbit/full-duplex, autoneg off, RX/TX pause on.
- Spark-facing RX ring 8160, TX ring 4096.
- Spark-facing adaptive RX on, rx-usecs 50. Link/DCB reset restored these
  defaults before the successful tests; the previous 8-us trial is not retained.
- Main-facing RX/TX rings 4096.
- Removed temporary secondary-to-main TBF cap. Original mq/pfifo_fast is back.
- Main and Spark qdiscs remain their original mq/fq_codel.

Successful 45-second concurrent tests (four streams per connection):

| Workload | Direction | Receiver Gbps | TCP retransmissions |
| --- | --- | ---: | ---: |
| Both peers sending to secondary | Main → secondary | 23.93 | 729 |
| Both peers sending to secondary | Spark → secondary | 22.76 | 632 |
| Secondary sending to both peers | Secondary → main | 24.08 | 0 |
| Secondary sending to both peers | Secondary → Spark | 23.25 | 20,953 |
| Both pairs fully bidirectional | Secondary → main | 24.35 | 0 |
| Both pairs fully bidirectional | Main → secondary | 20.52 | 565 |
| Both pairs fully bidirectional | Secondary → Spark | 22.83 | 452 |
| Both pairs fully bidirectional | Spark → secondary | 25.94 | 1,090 |

All measured port discard, missed-packet and CRC counters stayed flat across
the final tests. Pause counters increased on matching endpoints, establishing
that receiver backpressure was working. Existing historical counter values
are not new losses. TCP retransmissions were reduced, not eliminated.

Updated installer `deploy/remote-ingest/tune-dac-receive.sh` persists only this
qualified configuration and waits for effective pause state. It migrates the
old owned 20-Gbit TBF but refuses to replace unrelated qdisc policies.
Installed with --install-only because current live settings already matched;
boot unit enabled and syntax verified, not tested through reboot.

All temporary listeners removed. Both GPU containers still see their intended
GPUs, and storage routes remain on the 10-Gbit interface. No ingestion resume,
worker-role switch, model restart or further Spark reboot was performed.
These tests support a controlled worker pilot, not a long-duration stability
guarantee. Spark inference remains stopped for maintenance and must be restored
and tested before application-level worker readiness.

Rollback, if needed: restore the previous qualified installer/settings from
version history, including secondary-to-main TBF containment. Do not disable
pause at saturation without restoring containment and retesting port counters.

## October 20 receive-drop mitigation

Applied and retained only the changes that passed their targeted tests:
- Secondary Spark-facing port: RX ring 8160 (from 4096), adaptive RX
  coalescing off, RX interrupt delay 8 microseconds (from adaptive/50).
- Secondary main-facing port: outgoing TBF pacing at 20 Gbit/s,
  128-KB burst, 20-ms queue latency.
- Installer: `deploy/remote-ingest/tune-dac-receive.sh`. Installs
  `/usr/local/sbin/obtv-dac-throughput` and enables
  `obtv-dac-throughput.service`, ordered after existing DAC ring setup.
  Applied live and enabled with --no-reload; boot persistence is configured
  and syntax validated, not reboot-tested.

Increasing main RX rings to 8192 did not help and was reverted to 4096.
The 20-Gbit secondary-to-main pacing passed both individual and concurrent
transmit tests at 19.84–19.85 Gbps with zero TCP retransmissions, zero new main
RX physical discards, and zero local TBF drops.
TBF overlimits are deliberate pacing events, not discarded packets.

After receiver tuning, the secondary's RX missed/drop counters stayed flat
through subsequent single-link and concurrent tests. No new CRC errors.
Individual unpaced throughput remained about 26.88 Gbps main→secondary,
37.65 Gbps secondary→Spark, and 37.71 Gbps Spark→secondary, but these directions
still had TCP retransmissions.

**Not a full concurrent-load qualification:** when main and Spark simultaneously
sent unpaced to the secondary, receiver throughput was 23.61 and 22.45 Gbps,
with 57,918 and 264,152 sender retransmissions respectively. Physical receive
and CRC counters stayed flat. The secondary's dual-port card has a shared
PCIe 3.0 x8 path; this is a capacity consideration, not a proven explanation
of all retransmissions. Secondary softnet dropped count was zero.

A further trial pacing both senders at 20 Gbit/s did not qualify: main achieved
19.85 Gbps/47 retransmissions and Spark 12.82 Gbps/2,724 retransmissions.
Both trial sender qdiscs were reverted to their original mq/fq_codel setup.
No unproven limits were retained on main or Spark.

Final checks: test listeners removed, management/storage routes unchanged,
both secondary worker GPUs query successfully. No worker-role change, Spark
model restart, firmware change or host reboot performed. Further simultaneous
traffic diagnosis and application-level qualification remain necessary before
claiming readiness for the broader worker role.

Rollback of retained tuning (secondary only):
disable the new service with --no-reload, restore Spark-facing RX ring 4096 and
adaptive-rx on/rx-usecs 50, and replace main-facing root qdisc with mq.
Do not blindly remove other traffic-management settings if later work adds them.

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
