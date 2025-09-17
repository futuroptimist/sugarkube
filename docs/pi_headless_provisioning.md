# Headless provisioning playbook

This guide explains how to bring a sugarkube node online without attaching a
monitor or keyboard. It combines Raspberry Pi Imager presets, the
`scripts/cloud-init/` assets, and new verification helpers so first boot is
predictable.

## 1. Prepare network and credentials

1. Collect Wi-Fi or Ethernet details. If you use Wi-Fi, confirm the network is
   reachable near the Pi carrier and note the two-letter country code.
2. Generate or choose SSH keys dedicated to cluster administration. Store the
   public key in a secure location so you can inject it into Pi Imager presets
   and `cloud-init`.
3. Decide on a hostname pattern (for example `sugarkube-node-01`). The Pi image
   templates and `cloud-init` user-data both accept hyphenated hostnames.

## 2. Flash media with Raspberry Pi Imager

Follow [pi_imager_presets.md](pi_imager_presets.md) to import the
`sugarkube_headless_template.json` preset. Update the placeholders for hostname,
Wi-Fi, and SSH keys, then write the image to an SD card or USB SSD. The preset
points to the signed release artifacts published by `pi-image-release` so
sha256 verification happens automatically.

## 3. Inject custom cloud-init data (optional)

When you need to go beyond Pi Imager's basic settings—such as seeding API
tokens or enabling additional services—drop a custom
`scripts/cloud-init/user-data.yaml` alongside the flashed media:

```bash
cp scripts/cloud-init/user-data.yaml /mnt/boot/user-data
cp scripts/cloud-init/secrets.env.example /mnt/boot/secrets.env
```

Edit `secrets.env` with Wi-Fi passwords or Cloudflare tokens so sensitive data
stays off disk images committed to git. The default `user-data.yaml` already
includes placeholders that read from this environment file at first boot.

## 4. First boot verification

The `scripts/flash_pi_media.py` helper now supports `--report` to produce a
Markdown or HTML summary of every flash attempt. When paired with the new
`scripts/doctor.sh` health check you get a reproducible record of which image,
device, and checksum landed on the SD card.

```bash
make doctor DOCTOR_ARGS="--skip-checks"
```

The command above:

1. Ensures the latest release artifacts are reachable (`--dry-run`).
2. Performs a dry-run flash to a temporary file and saves
   `flash-report-*.md` in `~/sugarkube/reports/` with hashes and hardware IDs.
3. (Optional) Runs `scripts/checks.sh` to lint and test the repository.

Keep the generated report alongside the Pi's serial number so you can trace
issues later. Override the destination with
`SUGARKUBE_DOCTOR_REPORT_DIR=/path/to/reports` when needed.

## 5. Boot and monitor

1. Insert the flashed media into the Pi and power it on.
2. Wait a few minutes for cloud-init to expand the filesystem, apply the
   sugarkube manifests, and start k3s.
3. SSH using the preloaded key:

   ```bash
   ssh sugarkube@<hostname-or-ip>
   sudo journalctl -u cloud-init --no-pager
   sudo /opt/sugarkube/pi_node_verifier.sh --json
   ```

4. If the node fails verification, rerun `make doctor` to confirm the flash
   pipeline and inspect `/boot/first-boot-report` (created by upcoming
   checklist items) for clues.

## 6. Automate future runs

- Commit tuned versions of the presets and `user-data.yaml` to a private repo so
  new operators can get started instantly.
- Integrate `scripts/doctor.sh` into CI jobs that build images or check
  provisioning scripts; the dry-run keeps pipelines fast while still verifying
  signatures and generating reproducible flash reports.
- Combine the presets with the existing `Makefile` targets:

  ```bash
  make download-pi-image
  make flash-pi FLASH_DEVICE=/dev/sdX
  ```

  The `flash_pi_media.py` report keeps a trail of SHA-256 hashes and hardware
  IDs for compliance.

With these pieces in place the sugarkube Pi carrier becomes a plug-and-go
experience: download, flash, boot, and land directly in a healthy k3s cluster
with minimal manual intervention.
