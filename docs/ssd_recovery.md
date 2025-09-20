# SSD Recovery and Rollback

When an SSD migration stalls or the cloned drive fails later, falling back to the
original SD card helps the cluster boot cleanly while you investigate.
This guide explains how to inspect the current boot device, run the automated
rollback helper, and verify the system is back on the SD root filesystem.

## Before you begin

1. Make sure you still have the SD card that shipped with the `sugarkube`
   image inserted in the Raspberry Pi.
2. Connect a keyboard/monitor or SSH session so you can run commands locally.
3. Identify whether you are already booted from the SD card:
   ```bash
   findmnt /
   ```
   If the source column shows `mmcblk0p2` or `PARTUUID` that matches the SD
   card, you are already on the SD card and no rollback is necessary.

## Preview the rollback

The repository now ships `scripts/rollback_to_sd.sh`, which rewrites
`/boot/cmdline.txt` and `/etc/fstab` to point at the SD card and records the
current configuration for auditing. Run a dry run first to confirm what the
script will touch:

```bash
sudo ./scripts/rollback_to_sd.sh --dry-run
```

The helper reports:

- The current root and boot sources (and their PARTUUIDs).
- The detected SD card devices (`/dev/mmcblk0p1` and `/dev/mmcblk0p2` by
  default) and their PARTUUIDs.
- The backup directory under `/var/log/sugarkube/rollback/` that would store
  copies of `cmdline.txt` and `fstab`.

If your SD card is exposed on different device nodes (for example `mmcblk1` on
Compute Module carriers) override the defaults:

```bash
sudo ./scripts/rollback_to_sd.sh \
  --dry-run \
  --sd-boot-device /dev/mmcblk1p1 \
  --sd-root-device /dev/mmcblk1p2
```

## Apply the rollback

When you are satisfied with the dry run, remove `--dry-run` (and keep any
custom device overrides):

```bash
sudo ./scripts/rollback_to_sd.sh
```

Key behavior:

1. Backups of `/boot/cmdline.txt` and `/etc/fstab` are stored in
   `/var/log/sugarkube/rollback/<timestamp>/` before any edits.
2. `root=PARTUUID` in `cmdline.txt` is set to the SD card's root partition.
3. The `/` and `/boot` entries in `/etc/fstab` are rewritten to the SD card
   PARTUUIDs while other entries remain untouched.
4. A Markdown report is written to `/boot/sugarkube-rollback-report.md` that
   summarizes the changes and the detected devices.
5. `sync` is called to flush writes before exiting.

Finally, reboot the Raspberry Pi:

```bash
sudo reboot
```

After the system comes back, confirm the rollback succeeded:

```bash
findmnt /
cat /boot/sugarkube-rollback-report.md
```

The root filesystem should now point to `mmcblk0p2` (or your equivalent SD
partition). Review the report for the recorded devices, backup path, and next
steps.

## Using the Makefile and justfile shortcuts

Two convenience wrappers call the new helper:

- GNU Make:
  ```bash
  sudo make rollback-to-sd
  ```
- [just](https://github.com/casey/just):
  ```bash
  sudo just rollback-to-sd
  ```

Both commands respect the `ROLLBACK_ARGS` environment variable. For example, to
preview with a different SD root device:

```bash
sudo ROLLBACK_ARGS='--dry-run --sd-root-device /dev/mmcblk1p2' make rollback-to-sd
```

## Next steps after rolling back

- Investigate SSD health using `smartctl`, vendor dashboards, or by connecting
  the drive to another system.
- If you reattempt cloning later, keep the rollback backups around so you can
  compare the new configuration.
- After the next clone, run `sudo ./scripts/ssd_post_clone_validate.py` (or the
  `make`/`just` wrappers) to confirm `/etc/fstab`, `/boot/cmdline.txt`, and the
  EEPROM boot order all reference the SSD before pulling the SD card. The helper
  also records Markdown/JSON reports under `~/sugarkube/reports/ssd-validation/`
  for future incident reviews.
- Update your troubleshooting notes with the Markdown report stored on `/boot`
  so future incidents are easier to triage.
