---
personas:
  - hardware
  - software
---

# Sugarkube Pi Carrier Field Guide

The essentials to go from download to a healthy k3s cluster. Print on US Letter
or A4 and keep near the build bench.

## Fast Path (≈10 minutes)
1. Download: `just download-pi-image` (or `make download-pi-image`). Expect a
   `.img.xz` plus `.sha256` in `~/sugarkube/images/`.
2. Flash: `sudo just flash-pi FLASH_DEVICE=/dev/sdX` and watch for
   `Sync complete` with zero write errors.
3. Boot: Insert media, power the Pi, and wait for the green ACT LED to settle
   into a steady heartbeat (~1 Hz) after the first minute.
4. Verify: `ssh pi@pi.local sudo /usr/local/bin/pi_node_verifier.sh --json`. The
   `status` field should be `ok` and include `k3s_ready=true`.
5. Snapshot: Run `just clone-ssd CLONE_TARGET=/dev/sdX --resume` once an SSD is
   attached. Expect a final `Clone complete` message.

## Command Outputs
- `curl http://pi.local:12345/metrics` → HTTP 200 with Prometheus metrics lines
  such as `up 1` and `sugarkube_first_boot_status 1`.
- `kubectl --kubeconfig /boot/sugarkube-kubeconfig get nodes` → all nodes in
  `Ready` state within 3 retries.
- `journalctl -u ssd-clone --since -10m` → shows `ssd-clone.service completed`
  after a successful SSD migration.

## LED + Status Quick Reference
- Power steady, ACT blinking rapidly → booting; wait for ACT heartbeat before
  interacting.
- Power steady, ACT solid on >30s → check HDMI/serial; likely kernel panic.
- Power steady, ACT off → re-seat storage or reflash; Pi is not reading media.
- Ethernet steady + ACT heartbeat but no SSH → run `sugarkube-teams` or check
  `/boot/first-boot-report/` for verifier output.

## If Something Fails
- Re-run `just flash-pi-report FLASH_DEVICE=/dev/sdX` to capture Markdown/HTML
  logs under `~/sugarkube/reports/`.
- Review `/boot/first-boot-report/self-heal/` on the Pi for automated recovery
  attempts and escalations.
- Pull a support bundle: `just support-bundle SUPPORT_BUNDLE_HOST=pi.local` and
  attach the resulting archive to issues. Prefer CLI tooling? Run
  `python -m sugarkube_toolkit pi support-bundle --dry-run -- pi.local` first, then rerun without
  `--dry-run` when you're ready to collect logs.
- More guidance: [Pi Image Quickstart](./pi_image_quickstart.md) and
  [Pi Boot Troubleshooting](./pi_boot_troubleshooting.md).

## Optional noise suppression
- BlueZ may log SAP/vcp/mcp/bap plugin warnings on healthy systems. To quiet
  them, create an override with `sudo systemctl edit bluetooth.service` and set
  `ExecStart=/usr/lib/bluetooth/bluetoothd --noplugin=sap`, or add
  `DisablePlugins = sap` under `[General]` in `/etc/bluetooth/main.conf`.
