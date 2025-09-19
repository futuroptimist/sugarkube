# Raspberry Pi Imager presets

These presets pre-populate Raspberry Pi Imager's advanced options so each Pi
boots with the right hostname, user, Wi-Fi, and SSH keys. Copy one JSON file per
node, adjust the secrets, then render it into the Imager configuration with
`scripts/render_pi_imager_preset.py`.

## Folder layout

- `sugarkube-controller.preset.json` – control-plane defaults.
- `sugarkube-worker1.preset.json` – first worker defaults.
- `sugarkube-worker2.preset.json` – second worker defaults.

Each JSON file ships with safe placeholders (`ExampleNetwork`,
`ssh-ed25519 AAAA...ExampleOnly`) and a SHA-512 password hash for the string
`changeme`. Replace them before flashing.

## Rendering a preset

```bash
# 1. Prepare a secrets file so the CLI history never captures credentials
SSH_AUTHORIZED_KEY="$(cat ~/.ssh/id_ed25519.pub)"
cat <<EOF > ~/sugarkube/secrets.env
WIFI_SSID="your-ssid"
WIFI_PASSWORD="your-passphrase"
WIFI_COUNTRY=US
SSH_AUTHORIZED_KEY="$SSH_AUTHORIZED_KEY"
PI_PASSWORD="supers3cret"  # optional; hashes automatically
TIMEZONE=America/Los_Angeles
KEYBOARD_LAYOUT=us
EOF

# 2. Render the controller preset and apply it to Raspberry Pi Imager
python3 scripts/render_pi_imager_preset.py \
  --preset docs/templates/pi-imager/sugarkube-controller.preset.json \
  --secrets ~/sugarkube/secrets.env \
  --output ~/sugarkube/imager-presets/sugarkube-controller.ini \
  --apply
```

The script reads the JSON template, merges overrides from `secrets.env` and CLI
flags, hashes any plain-text password, then:

1. Writes an `.ini` snippet you can track in Git or share internally.
2. Updates `~/.config/Raspberry Pi/Imager.conf` so Raspberry Pi Imager pre-fills
   the advanced options for the next flash.

Repeat the command with the worker preset(s); pass `--hostname` to override the
value inside the JSON without editing it in place.

## Updating placeholders

- **Wi-Fi:** `--wifi-ssid`, `--wifi-password`, and `--wifi-country` flags override
  the JSON to avoid leaking credentials into Git history.
- **SSH keys:** provide one or more `--ssh-key-file` arguments, or populate
  `SSH_AUTHORIZED_KEYS` in `secrets.env` separated by newlines.
- **Password hashes:** supply either `PI_PASSWORD_HASH` (already hashed) or
  `PI_PASSWORD` (plain text). The script uses `sha512-crypt` so Raspberry Pi OS
  accepts the value on first boot.
- **Time zone & keyboard:** override with `--timezone`, `--keyboard-layout`, and
  `--keyboard-variant`.

Run `python3 scripts/render_pi_imager_preset.py --help` for all switches.
