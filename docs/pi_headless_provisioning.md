# Headless Sugarkube Provisioning

This guide explains how to provision a fresh sugarkube Pi image without attaching a monitor or keyboard. It uses `cloud-init` user data and a small `secrets.env` helper to inject Wi-Fi credentials, SSH keys, and optional API tokens on the first boot.

## Overview

1. Download the latest signed sugarkube image.
2. Create a bootable SD card or SSD.
3. Drop a templated `user-data` file and optional `secrets.env` onto the `/boot` partition.
4. Boot the Pi and wait for `cloud-init` to apply settings.
5. Verify cluster readiness using the bundled `pi_node_verifier.sh` script.

## Prepare the image

```bash
make download-pi-image
sudo make flash-pi FLASH_DEVICE=/dev/sdX
```

Alternatively, run `make doctor` first to confirm tooling is installed and dry-run safe.

## Create cloud-init configuration

Copy the example configuration and edit the placeholders:

```bash
cp docs/templates/cloud-init/user-data.example user-data
nano user-data
```

Recommended options:

- Set a unique hostname (`sugarkube-node01`).
- Provide a privileged admin user. The example uses `sugaradmin` with SSH key-only authentication.
- Configure Wi-Fi credentials using `wifis`.
- Inject optional environment variables for services like Cloudflare Tunnels or token.place secrets.

The base image now writes a sanitized kubeconfig to `/boot/sugarkube-kubeconfig` once k3s is
online, so you can collect cluster endpoints without SSH. The default template still seeds
`/boot/sugarkube/` with placeholders for bootstrap tokens or additional secrets you may want to
mirror on first boot.

## Inject secrets safely

Sensitive values (API keys, Cloudflare tokens) belong in `secrets.env`. Store it alongside `user-data` on the boot partition.

```bash
cat <<'ENV' > secrets.env
# CLOUDFLARED_TOKEN value goes here
# TOKEN_PLACE_SIGNING_KEY value goes here
ENV
```

Replace each placeholder comment with a `NAME=value` pair before booting.
`cloud-init` sources the file at first boot, exports the variables into `/etc/environment`, and removes the plaintext copy once provisioning finishes. Regenerate the file for each cluster to avoid reusing credentials.

## Flash media and copy configs

After running `make flash-pi`, mount the boot volume and copy the configs:

```bash
sudo mount /dev/sdX1 /mnt/pi-boot
sudo cp user-data /mnt/pi-boot/user-data
sudo cp secrets.env /mnt/pi-boot/secrets.env # optional
sudo umount /mnt/pi-boot
```

For SSD installs, repeat with the target device (e.g., `/dev/sdY1`).

## First boot verification

1. Power on the Pi.
2. Wait for the `first-boot` LEDs to settle (steady green). The new
   `first-boot.service` handles filesystem expansion, runs the verifier, and
   drops reports under `/boot/first-boot-report/` (HTML, JSON, Markdown, and the
   raw log).
3. Review `/boot/first-boot-report/index.html` or `status.json` for status. When
   ready, SSH in:

```bash
ssh sugaradmin@sugarkube-node01.local
```

4. Run the verifier:

```bash
sudo /usr/local/bin/pi_node_verifier.sh --full
```

5. (Optional) Copy `/boot/sugarkube-kubeconfig` from another machine to share cluster endpoints
   with teammates. The export redacts client keys and tokens—regenerate a full admin config later
   using `sudo k3s kubectl config view --raw` before authenticating from a workstation.

Successful runs leave `/boot/first-boot-report/status.json`,
`/boot/first-boot-report/verifier.json`, and `/var/log/sugarkube/first-boot.ok`
for later auditing.

## Recovering or rerunning provisioning

If provisioning fails:

- Inspect `/var/log/cloud-init.log` and `/boot/first-boot-report/*.log`.
- Rerun `cloud-init clean` followed by `sudo reboot`.
- Re-copy `user-data` and `secrets.env` if they were scrubbed after a successful run.

Store sanitized copies of `user-data` in a secure secrets vault so they can be reused during disaster recovery.
