# Headless Sugarkube Provisioning Guide

This guide shows how to boot a fresh `pi_carrier` node, inject credentials, and
join the k3s cluster without connecting a keyboard or monitor. It builds on the
Raspberry Pi Imager presets in [`docs/pi_imager_presets/`](pi_imager_presets/)
and the post-flash verifier that ships with the sugarkube image.

## 1. Prepare secrets without editing the repository

Create a working directory that will never be committed:

```bash
mkdir -p ~/sugarkube/provisioning
cd ~/sugarkube/provisioning
```

Copy one of the presets and edit it locally:

```bash
cp /path/to/sugarkube/docs/pi_imager_presets/sugarkube-wifi.json .
$EDITOR sugarkube-wifi.json
```

Update the following fields before flashing:

- Wi-Fi SSID, passphrase, and country code entries  
- `ssh.authorized_keys` (add one line per key)  
- Optional `cloud_init.user_data` secrets (uncomment the `write_files` section)  

When finished, record the checksum so you can audit the preset later:

```bash
sha256sum sugarkube-wifi.json > sugarkube-wifi.json.sha256
```

## 2. Inject cloud-init configuration

Place additional cloud-init configuration alongside the preset so the
provisioning wrapper can copy it into `/boot/user-data` before first boot.  
Example `user-data` snippet for Wi-Fi credentials, Cloudflare tokens, and the
k3s shared token placeholder:

```yaml
#cloud-config
write_files:
  - path: /var/sugarkube/secrets.env
    owner: root:root
    permissions: '0600'
    content: |
      CLOUDFLARE_TOKEN placeholder: <your-token-here>
      DSPACE_LICENSE placeholder: <your-license-here>
  - path: /var/lib/rancher/k3s/server/token
    owner: root:root
    permissions: '0600'
    content: |
      K1exampletokenplaceholder
runcmd:
  - [ "/usr/local/bin/projects-compose.sh", "--ensure" ]
  - [ "/usr/local/bin/pi_node_verifier.sh", "--non-interactive" ]
```

The sugarkube image enables the [`cloud-init`](https://cloud-init.io/)
`NoCloud` data source. Any `user-data` file placed on the boot volume runs on
first boot without manual edits inside the repository.

## 3. Use the flash-and-report wrapper

The new [`scripts/flash_and_report.py`](../scripts/flash_and_report.py) helper
links everything together:

```bash
python3 scripts/flash_and_report.py \
  --image ~/Downloads/sugarkube.img.xz \
  --device /dev/sdX \
  --report-dir ~/sugarkube/reports \
  --cloud-init-expected sugarkube-wifi.json \
  --cloud-init-observed user-data
```

The wrapper automatically decompresses the image, flashes the target device,
verifies checksums, and captures a Markdown + HTML report listing:

- Hardware identifiers for the selected device (model, size, bus)  
- SHA-256 sums for the source image, expanded image, and flashed media  
- A unified diff between your preset and the applied `user-data`  
- The full flashing log from `flash_pi_media.py`  

Reports are stored as `flash-report-YYYYmmdd-HHMMSS.{md,html,json}` inside the
chosen `--report-dir`. Include the Markdown or JSON files when opening support
requests so the maintainers can reproduce your environment.

## 4. Boot and validate

1. Insert the flashed media into the Pi or SSD sled and power on.  
2. Wait for the Pi to appear on the network (mDNS hostname `sugarkube.local`).  
3. Run `ssh sugaradmin@sugarkube.local sudo /usr/local/bin/pi_node_verifier.sh`.  
4. Review `/boot/first-boot-report/summary.json` for k3s readiness, token.place
   health, and dspace status.  

If anything fails, capture the report artifacts and run the headless verifier
again after a reboot. The flash report plus `/boot/first-boot-report` give the
support team enough data to triage issues without physical access to your Pi.
