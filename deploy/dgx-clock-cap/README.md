# DGX diagnostic clock cap

Run `install.sh` as root on the DGX Spark. It applies GPU 0's requested
300–2100 MHz range immediately and installs a boot-enabled service that Docker
requires before starting containers. A failed cap blocks Docker on subsequent
boot rather than silently starting inference uncapped.

The installer deliberately avoids daemon-reload and container restarts because
this host uses NVIDIA runtime devices without explicit mappings. The new boot
dependencies are read on the next boot. Do not claim a reboot verification
until one has actually been performed.

Clock readback may take a few seconds to settle. The GPU can select a supported
step below the requested upper limit (historically 2093 MHz). The advertised
maximum GPU clock is not the active locked-clock limit.

This is thermal/current containment and an A/B diagnostic, not a proven repair.
Continue external health recording. No crash-kernel, driver, fan, or network
settings are changed by this installer.

To remove only after authorization: remove the Docker drop-in and disable the
boot service, then reset locked GPU clocks with `nvidia-smi -i 0 -rgc`.
Service-manager changes on a running GPU host require care; do not blindly
daemon-reload while containers are using unpinned NVIDIA device permissions.
