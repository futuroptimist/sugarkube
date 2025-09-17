# Raspberry Pi Imager Presets for Sugarkube

These presets preload the values that the `pi_carrier` cluster expects so you can
flash media with Raspberry Pi Imager in a single step.  Each JSON file can be
imported via **Raspberry Pi Imager → Settings (gear icon) → Choose OS custom
preset**.

The templates intentionally keep obvious placeholders so you can update Wi-Fi
credentials and SSH keys before flashing.  Replace the placeholder values with
your own secrets **without** committing them back to the repository.

## Available presets

| File | Purpose |
| ---- | ------- |
| [`sugarkube-wifi.json`](sugarkube-wifi.json) | Enables Wi-Fi, preloads hostname/username, and adds an SSH public key. |
| [`sugarkube-ethernet.json`](sugarkube-ethernet.json) | Optimised for hard-wired installs where Wi-Fi is disabled. |

Both presets configure:

- Hostname `sugarkube`
- User `sugaradmin` with sudo access
- SSH key-only authentication (interactive prompts remain disabled)
- Locale and keyboard defaults (`en_US`, `us`)
- Timezone `UTC`
- First-boot script `sudo /usr/local/bin/pi_node_verifier.sh` to confirm the
  cluster health

## Customisation checklist

1. **SSH keys:** replace `ssh-ed25519 AAAA...` with one or more of your public
   keys.  Raspberry Pi Imager automatically writes them to
   `/home/sugaradmin/.ssh/authorized_keys`.
2. **Wi-Fi network:** update the `ssid`, passphrase, and country fields in the
   Wi-Fi preset.  Set `hidden` to `true` if the SSID does not broadcast.
3. **Optional cloud-init secrets:** uncomment the `user-data` stanza at the end
   of the file to inject secrets (Cloudflare tokens, registry credentials).  These
   values live only on the imaged media and never enter version control.
4. **Regenerate checksums:** run `sha256sum <preset>.json` after editing so you
   can detect accidental changes later.

## Applying the preset

1. Launch Raspberry Pi Imager `1.7` or newer.
2. Select **Use custom** and pick the latest sugarkube release image.
3. Click the gear icon, choose **Load settings from file**, and select one of the
   presets in this directory.
4. Confirm the summary matches your edits and flash as usual.  The generated
   `/boot/first-boot-report` will record that the preset was applied.

For more advanced provisioning (multiple nodes or secrets rotation) see
[`../pi_headless_provisioning.md`](../pi_headless_provisioning.md).
