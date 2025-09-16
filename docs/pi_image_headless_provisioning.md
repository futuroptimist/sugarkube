# Headless Provisioning Checklist

The sugarkube image now ships with a first-boot report generator and a
single-file installer that fetches releases with checksum verification.
This guide shows how to combine those tools so a Pi can be provisioned
without ever attaching a keyboard, mouse, or display.

## 1. Fetch the image non-interactively

Download and expand the latest release with the installer script. The
command uses `curl | bash` but only runs trusted code from this
repository. Add `--dry-run` to inspect the actions first.

```bash
curl -fsSL https://raw.githubusercontent.com/futuroptimist/sugarkube/main/scripts/install_sugarkube.sh | bash
```

The script will:

1. Install the GitHub CLI (`gh`) when it is missing (prompting first).
2. Download the newest `sugarkube.img.xz` release and checksum.
3. Verify the hash and expand it to `~/sugarkube/images/sugarkube.img`.

Set a custom destination with `--output /path/to/sugarkube.img`.

## 2. Record Wi-Fi and tunnel secrets without editing the repo

Create a directory outside the repository to store credentials. This
guide uses `~/sugarkube-secrets/`.

```bash
mkdir -p ~/sugarkube-secrets
cat <<'ENV' > ~/sugarkube-secrets/secrets.env
export WIFI_COUNTRY="US"
export WIFI_SSID="MyNetwork"
export WIFI_PASSPHRASE="REPLACE_WITH_WIFI_PASSPHRASE"
ENV
chmod 600 ~/sugarkube-secrets/secrets.env
```

> **Tip:** The installer never reads these values automatically. Sourcing
> `secrets.env` keeps them in your shell session without committing them
> to git.

Add your Cloudflare token later with a text editor by copying the same line you
would place inside `/opt/sugarkube/.cloudflared.env`. Preserve the `0600` file
mode so secrets stay private.

```bash
set -a
source ~/sugarkube-secrets/secrets.env
set +a
```

The Wi-Fi variables follow the format expected by `wpa_supplicant.conf`.
The Cloudflare token matches the value used in
`/opt/sugarkube/.cloudflared.env` on the Pi.

## 3. Inject secrets into the image before flashing

With the raw image expanded, mount it locally and drop in the
configuration. Locate the boot partition offset with `fdisk` and then
mount it.

```bash
RAW_IMG=${RAW_IMG:-$HOME/sugarkube/images/sugarkube.img}
BOOT_OFFSET=$(sudo fdisk -l "$RAW_IMG" | awk '/^Device.*Start/ {next} /img1/ {print $2; exit}')
BOOT_BYTES=$((BOOT_OFFSET * 512))
sudo mkdir -p /mnt/sugarkube-boot
sudo mount -o loop,offset="$BOOT_BYTES" "$RAW_IMG" /mnt/sugarkube-boot
```

1. **Wi-Fi** – drop a standard `wpa_supplicant.conf` onto the boot
   partition so cloud-init applies it on first boot.

   ```bash
   cat <<WPA | sudo tee /mnt/sugarkube-boot/wpa_supplicant.conf >/dev/null
   country=${WIFI_COUNTRY}
   ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
   update_config=1

   network={
       ssid="${WIFI_SSID}"
       psk="${WIFI_PASSPHRASE}"
   }
   WPA
   ```

2. **Cloudflare Tunnel** – stage the token so the container starts
   automatically. Create `/mnt/sugarkube-boot/sugarkube/.cloudflared.env`
   with the same contents you would place on the Pi (one line containing the
   tunnel token). Ensure the file permissions are `0600`.

3. **Optional:** Store an SSH public key for the `pi` user.

   ```bash
   mkdir -p ~/.ssh
   cat ~/.ssh/id_ed25519.pub | sudo tee /mnt/sugarkube-boot/ssh_authorized_keys >/dev/null
   ```

When finished, unmount the image.

```bash
sudo umount /mnt/sugarkube-boot
```

Flash the prepared image with Raspberry Pi Imager or `dd`.

## 4. Alternative – embed secrets while building

If you build images locally the same secrets can be injected with
environment variables so you never edit files in the repository.

```bash
cp scripts/cloud-init/user-data.yaml ~/sugarkube-secrets/user-data.yaml
# Edit ~/sugarkube-secrets/user-data.yaml and fill in the Cloudflare token line.
TUNNEL_TOKEN_FILE=~/sugarkube-secrets/cloudflared.token \
  CLOUD_INIT_PATH=$HOME/sugarkube-secrets/user-data.yaml \
  ./scripts/build_pi_image.sh
```

Where `~/sugarkube-secrets/cloudflared.token` is a plain-text file containing
only your tunnel token.

The build script validates the custom `user-data` file, embeds the
Cloudflare token, and produces a release-quality `.img.xz` archive with
matching checksums.

## 5. First boot expectations

On the first boot the Pi now:

- Expands the root filesystem and waits for networking.
- Runs `pi_node_verifier.sh --json`.
- Copies the kubeconfig and cluster token to `/boot/sugarkube-kubeconfig.yaml`
  and `/boot/sugarkube-node-token`.
- Writes JSON, HTML, and plain-text summaries to `/boot/first-boot-report/`
  and `/boot/first-boot-report.txt`.

If Wi-Fi credentials or the Cloudflare token fail, those tasks show
`failed` in the report so you can fix the secrets without guessing which
step broke.

## 6. Resetting credentials later

Because the secrets live on the FAT boot partition you can swap or revoke
credentials at any time:

- Update Wi-Fi by editing `wpa_supplicant.conf` from another machine.
- Rotate Cloudflare tokens by replacing
  `/boot/sugarkube/.cloudflared.env` before rebooting.

The first-boot service only runs once, but you can manually re-run the
reporting script via:

```bash
sudo /usr/local/sbin/sugarkube-first-boot.sh
```

It safely regenerates the HTML/JSON status files without rerunning cloud-init.
