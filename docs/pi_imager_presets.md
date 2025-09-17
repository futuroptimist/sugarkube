# Raspberry Pi Imager presets for sugarkube

The `hardware/pi_imager_presets/` directory ships ready-to-edit JSON templates
for Raspberry Pi Imager's "Advanced options" dialog (`Ctrl` + `Shift` + `X`).
Loading one of these files pre-populates the hostname, default account, Wi-Fi
credentials, and SSH keys so a sugarkube node can boot without ever attaching a
monitor or keyboard.

## Available templates

| File | Scenario |
| ---- | -------- |
| `sugarkube_headless_template.json` | Configure hostname, Wi-Fi, locale, and SSH for unattended installations. |
| `sugarkube_ethernet_template.json` | Same defaults without Wi-Fi when the Pi connects via Ethernet. |

Both presets reference the latest published sugarkube image from GitHub
Releases. Update the `image.source` URL and `image.checksum` when you want to
pin to an older release.

## How to use the templates

1. Launch Raspberry Pi Imager (v1.8 or newer).
2. Choose **Operating System → Use custom** and select any sugarkube image.
3. Insert your SD card or SSD adapter and select it under **Storage**.
4. Press `Ctrl` + `Shift` + `X` to open **Advanced options**.
5. Click **Load settings from file…** and pick one of the JSON templates.
6. Replace placeholder values before saving:
   - `wifi_ssid` / `wifi_password` (headless template only).
   - `authorized_keys` — paste one or more SSH public keys.
   - `password` — optionally set a fallback password (Imager will hash it).
   - `timezone`, `keyboard`, `language` — match your locale.
7. Optional: set `image.checksum` to the `sugarkube.img.xz.sha256` value from
the release notes for reproducibility.
8. Click **Save** to persist the changes, then **Write** to flash the media.

When Raspberry Pi Imager loads a template it validates field names and removes
placeholders that are left blank. Invalid JSON will surface an error before any
media is written.

## Tips for reproducible presets

- Store customised copies alongside team-specific SSH keys, rotating them
  whenever credentials change.
- Keep the presets under version control so you can diff Wi-Fi or hostname
  changes before provisioning new nodes.
- Use `scripts/generate_release_manifest.py` to fetch the exact checksum and
  git metadata for a release; copy the SHA-256 into the template.

## Relationship with cloud-init

The templates complement the repository's `scripts/cloud-init/` assets. The
values injected through Raspberry Pi Imager map to the same settings consumed
by `user-data.yaml`, so you can reuse the same usernames, passwords, and
authorized keys whether you flash with Imager or customise `cloud-init`
directly.
