# DGX host outage investigation — 2026-10-19

## Confirmed observations

- Spark returned with a new OS boot at approximately 03:31 Pacific on October 19.
- Main server recorded its direct link going down October 18 at 10:30:29 Pacific
  and returning October 19 at 03:31:41.
- The Spark's previous journal ends at October 18 10:30:01, without an orderly
  shutdown record. Several preceding boots similarly end abruptly. This is not
  merely a restarted vLLM container or a single application timeout.
- The three inspected previous boots contain no matching kernel panic,
  OOM-killer, NVIDIA Xid, or watchdog-lockup report. One has an NVIDIA allocation
  failure roughly 25 minutes before its journal ends; that is not proof of causation.
- The previously applied GPU cap is not currently enforced: live clocks exceeded
  2.1 GHz, and no boot-time clock-lock script/service was found in the inspected
  standard systemd, local executable, and cron locations.
- Crash capture is not armed despite an active kdump service: USE_KDUMP=0,
  kexec_crash_loaded=0, and crashkernel=1G-:0M. No pstore/crash dump was available.

## Telemetry limitations

The original external 24-hour recording ended October 11. Its maximum sampled
SoC thermal-zone temperature was 94.2°C, but that sample was not immediately
before the latest outage and does not prove a thermal cutoff. Its sampled
available memory remained above approximately 29 GiB; this cannot rule out
memory failures on later dates.

Recording was renewed for 24 hours on October 19, on the main server rather
than the Spark. The existing forced-command health key had expired; only its
expiry was extended, preserving restrictions. A fresh successful sample was
verified at 10:37:32 UTC. Samples retain boot ID, GPU clocks/temperature/power,
all exposed thermal zones, available RAM/swap, ping, link and model HTTP status.

At the last inspection the host was reachable and vLLM was progressing through
checkpoint loading (7 of 15 shards), not yet serving the model endpoint. No
restart was issued to interrupt that startup.

## Conclusion and corrective plan

There is evidence of repeated abrupt host interruptions, not enough evidence
to distinguish power/protection shutdown from an unrecorded hard kernel failure.
Power/SoC thermal behavior deserves investigation given previous heat reports
and absent clock mitigation. Driver/kernel failure remains an alternative.
The known secondary-DAC CRC issue does not by itself explain a new OS boot.

Next steps:
1. Restore a reboot-persistent 300–2100 MHz diagnostic cap if authorized, before
   model startup, and compare externally recorded stability under the same load.
2. Configure supported crash-kernel reservation and enable kdump in a scheduled
   reboot, then verify an actual loaded crash kernel. Do not claim that the
   currently active kdump service provides capture.
3. Verify power adapter/connection and cooling physically. If abrupt failures
   continue with bounded clocks, use collected evidence to isolate adapter,
   board, firmware and kernel causes rather than repeatedly resetting ingestion.
