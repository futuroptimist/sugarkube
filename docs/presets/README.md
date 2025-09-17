# Raspberry Pi Imager presets

The JSON files in this directory pre-fill Raspberry Pi Imager with the latest
sugarkube release URL and headless configuration defaults.

## Usage

1. Copy the preset into Raspberry Pi Imager's configuration directory:
   - **Linux:** `~/.config/Raspberry Pi/Imager/presets/`
   - **macOS:** `~/Library/Application Support/Raspberry Pi/Imager/presets/`
   - **Windows:** `%APPDATA%\Raspberry Pi\Imager\presets\`
2. Launch Raspberry Pi Imager and select the **Sugarkube Headless** preset from
   the **Settings → Presets** menu.
3. Update the placeholders for Wi-Fi SSID, passphrase, and remote login
   credentials before flashing. The preset mirrors the structure used by
   `scripts/cloud-init/` so values stay in sync with `secrets.env`.

The preset points to the GitHub Releases `sugarkube.img.xz` artifact. Replace the
`sha256` and `uncompressed_size` fields with the values from the manifest if you
want Raspberry Pi Imager to enforce checksum verification.
