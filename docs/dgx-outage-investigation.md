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
1. Compare externally recorded stability under the same load with the
   user-authorized persistent 300–2100 MHz diagnostic cap now installed.
2. Configure supported crash-kernel reservation and enable kdump in a scheduled
   reboot, then verify an actual loaded crash kernel. Do not claim that the
   currently active kdump service provides capture.
3. Verify power adapter/connection and cooling physically. If abrupt failures
   continue with bounded clocks, use collected evidence to isolate adapter,
   board, firmware and kernel causes rather than repeatedly resetting ingestion.

## Clock containment applied

The user authorized a reboot-persistent 2100-MHz upper limit. Deployment sources
are in `deploy/dgx-clock-cap/`. The cap was applied live, with a settled readback
of 2093 MHz on the host and both model containers. A real generation request
returned HTTP 200 and READY. Container start timestamps were unchanged.

The enabled boot service is a required predecessor of Docker, so failed clock
locking prevents Docker startup rather than silently allowing uncapped models.
No daemon-reload, model restart, or host reboot was performed: boot configuration
was enabled with --no-reload to avoid NVIDIA container device-access disruption.
Persistence is configured and unit syntax verified, but has not yet been
tested through an actual reboot. Crash-capture configuration remains unchanged.

## October 19, 12:10–12:15 Pacific verification

The production database contains exactly 10,000 assets, all with status ready:
9,660 videos (H.264/HEVC), 271 images and 69 audio assets. The library-limit
checkpoint is reached with zero reserved slots; the catalog runner is paused.
There are no pending/running processing jobs. No ingestion was resumed.

Readiness caveats:
- Checking the preferred proxy/original paths from the API container found
  9,993 nonempty files and seven missing video paths under /curator. Their
  original paths are also absent. This is a filesystem check, not a full decode
  or playback test.
- Fourteen assets have historical failed jobs without a later success of that
  same job type. Ten involve analysis; all ten nevertheless have transcript
  and scene rows. These errors do not alone prove all fourteen are unusable.
- Processing-stage/progress fields are inconsistent with the ready flag:
  8,967 say diarized/75%, 531 complete/100%, 382 visual_embed_complete/90%,
  116 face_detect_complete/92%, four face_detect/85%. Independent stage tasks
  write these fields; do not equate these values with live jobs or silently
  relabel them to make the benchmark look complete.

Missing-file asset IDs:
575998ba-5843-4c22-905e-93c29798469b,
027fc651-8663-49cb-aa40-004b09842a28,
319f50e4-d975-4229-834b-55ebe0ba99ed,
6f2062fb-3e4a-4033-ad18-84c558ac1b30,
985aeb47-c3ea-4714-bb03-2562c6bf304a,
f89012ca-f2fa-49f8-8dcb-e06496421261,
7dc1002f-8fdc-42fc-81f6-204893d66f68.

Spark testing:
- Two concurrent inference requests repeated for 181.65 seconds:
  44/44 succeeded, generating 11,264 tokens.
- An additional long-context request (6,379 input tokens) returned HTTP 200
  in 6.7 seconds, generating 113 tokens.
- External ten-second samples during the test: peak GPU 61 C, maximum exposed
  thermal zone 75.8 C, peak sampled GPU power 29.51 W, clocks at most 2093 MHz.
  No SSH/model health failures or boot-ID change. No new matching kernel
  GPU/OOM/panic/hardware-error messages found.
- This is a bounded inference test, not a maximum-power hardware burn-in.
  It did not reproduce or establish the cause of shutdowns.
- Today's earlier recording had 3,037 successful samples across one boot
  through 12:11 Pacific, peak GPU 74 C and exposed thermal zone 85.6 C.
  Seven above-cap samples were confined to 03:45–03:46 Pacific, before the
  settled cap; they do not demonstrate subsequent cap failure.
- NVMe reports 56 lifetime unsafe shutdowns, zero media/errors-log entries,
  zero critical warning, 100% available spare. Unsafe shutdowns support abrupt
  interruptions but cannot distinguish deliberate power cuts from failures.
- Crash kernel remains unloaded. Secure Boot is enabled. Official NVIDIA
  field diagnostics are not installed and require temporarily disabling Secure
  Boot, rebooting and releasing GPU workloads. No security change, reboot,
  driver update, container restart or uncapping was performed.
- Some DAC ports continue to flap while the host and main inference path stay
  online. That is a separate connectivity problem, not proof of host shutdown.

Next diagnostic step: obtain a maintenance window for official NVIDIA field
diagnostics (approximately 30 minutes plus reboot/setup), restore Secure Boot
afterward, and establish working crash capture. Check the physical power supply
and cooling as part of that window. Do not declare a thermal/power root cause
from the successful capped test.

## Authorized maintenance preparation, October 19 afternoon

The user approved taking the Spark offline with a firmware-console operator.
Installed official dgx-spark-fieldiag 1.0.9-1 plus fio, memtester and stress-ng.
Inspected this package's actual default spec: GPU, C2C, CPU, power, thermal,
SSD and memory tests; no CX7 action. Do not install/replace the network-driver
stack merely because newer online documentation describes a CX7 prerequisite.

Before firmware reboot:
- Confirmed library still 10,000 ready, catalog paused and limit latched.
- Stopped vllm and obtvai-worker-bagel-1; temporarily set restart=no on both.
  Original policies saved on Spark in
  /opt/obtv-fielddiag-maintenance/original-container-policies.txt:
  vllm unless-stopped; BAGEL on-failure, maximum retry count zero.
- Disabled the previously enabled, currently inactive spark.service and
  obviu-spark-ai.service for maintenance, without daemon-reload.
  Original enabled states saved in original-service-enabled.txt beside policies.
- Preserved boot-time GPU cap and Docker dependency. Unit validation passed.
- Main server can reach management SSH at 192.168.200.248, an alternative to
  DAC SSH if the diagnostic disrupts GPU/NIC drivers.

The diagnostic unloads NVIDIA drivers and loads MODS: the normal nvidia-smi
clock lock cannot be promised during testing. The user has been informed;
confirm consent for diagnostic-managed clocks before launching stress tests.
Do not automatically start tests or model containers after the firmware reboot.
Confirm Secure Boot disabled, then enter multi-user mode and run the diagnostic
with persistent logs. Extra thermal/power/clock logging is supported by the
installed wrapper. If interrupted, NVIDIA requires a power cycle before retry.

After tests: restore Secure Boot through firmware, reboot, verify cap service
and actual clock behavior before restoring original container restart policies
and starting models. Restore original enabled states for the two legacy Spark
services, preserving their pre-maintenance inactive state until normal reboot.
Verify inference and external recording; catalog must remain paused at 10,000.
