# Headless provisioning guide

This guide walks through preparing a sugarkube Pi without ever plugging in a
keyboard, mouse, or display. It combines the Raspberry Pi Imager preset helper,
cloud-init overrides, and the flashing tooling so that a newly booted Pi joins
your cluster immediately.

## 1. Generate a Raspberry Pi Imager preset

Use the preset generator to capture your hostname, Wi-Fi credentials, and SSH
keys in a format that Raspberry Pi Imager understands:

```bash
SUGARKUBE_PRESET_SECRET_FILE=~/secure/sugarkube/passphrase.txt \
  python scripts/create_pi_imager_preset.py \
  --hostname sugarkube-pi \
  --username sugarkube \
  --wifi-ssid "YourNetwork" \
  --wifi-pass\
word "super-secret" \
  --wifi-country US \
  --ssh-key-file ~/.ssh/id_ed25519.pub \
  --pretty \
  --output ~/sugarkube/presets/sugarkube-imager.json
```

Key tips:

- Store sensitive material (credentials such as Wi-Fi PSK) outside the repository and
  reference them with `SUGARKUBE_PRESET_SECRET_FILE` or the built-in CLI key-file
  flags to keep them off the command line history.
- Provide a `$6$...` style Linux credential hash via the dedicated CLI option to
  avoid hashing on a non-POSIX system.
- The command writes JSON that Raspberry Pi Imager can import via
  **Settings → Advanced Options → Load preset**.

The repository ships an example preset in `presets/sugarkube-preset.example.json`.
Use it as a reference only—replace every placeholder before flashing real media.

## 2. Layer cloud-init secrets for headless boot

The default `scripts/cloud-init/user-data.yaml` provisions k3s, token.place, and
dspace. Provide environment specific values without modifying tracked files by
creating an override:

```bash
cat <<'YAML' > ~/sugarkube/cloud-init/user-data.override.yaml
#cloud-config
sugarkube:
  wifi_psk: "super-secret"
  cloudflare_api_id: "your-cloudflare-id"
  tp_admin_contact: "admin@example.org"
YAML
```

Before flashing, validate the override matches the baseline cloud-init file:

```bash
python scripts/flash_pi_media.py \
  --image ~/sugarkube/images/sugarkube.img.xz \
  --device /tmp/loop.img \
  --assume-yes --keep-mounted --no-eject \
  --report \
  --cloud-init-override ~/sugarkube/cloud-init/user-data.override.yaml
```

The command performs a dry-run flash to a loopback file, verifies the checksum,
and writes Markdown/HTML reports with a unified diff between the repo baseline
and your override. Review the diff before touching real hardware.

## 3. Flash completely headless

Once the preset and cloud-init override look good:

1. Open Raspberry Pi Imager, choose **Use custom** and select the
   `sugarkube.img.xz` release.
2. Load the generated preset (`sugarkube-imager.json`) so hostname, user, Wi-Fi,
   and SSH keys populate automatically.
3. Flash the media. The Pi will boot directly onto the network with SSH enabled.

You can script the entire workflow locally via `make flash-pi` or run a
pre-flight check with `make doctor`.

## 4. Keep the process repeatable

- Store presets and cloud-init overrides in a secure location (e.g., credential
  manager, encrypted dotfiles repository).
- Re-run the preset generator whenever credentials rotate. The script updates
  files in-place, so Pi Imager always imports the latest configuration.
- Commit diffs of non-sensitive overrides or presets to your internal fork to
  maintain an audit trail.

## 5. Troubleshooting

- **Imager rejects the preset** – Ensure the JSON still contains valid SSH keys
  and that the credential hash begins with `$6$`.
- **Wi-Fi fails to connect** – Double check the `wifi-country` code and that the
  SSID/PSK pair is correct. Hidden networks often require the
  `--wifi-hidden` flag.
- **No diff in the report** – If the flash report shows “No differences
  detected,” the override matches the baseline. Confirm you passed the correct
  file path or intentionally changed values.

## 6. Validate the workstation with `make doctor`

Run `make doctor` before touching hardware. The helper performs a dry-run
download, flashes a synthetic image to a loopback file, verifies checksums, and
executes `pre-commit run --all-files` so you know the repo state is clean. The
flash report lands in `~/sugarkube/reports` unless you override the
`SUGARKUBE_REPORT_DIR` environment variable.

With these steps the Pi images boot unattended, join the network, and launch the
cluster services without manual intervention.
