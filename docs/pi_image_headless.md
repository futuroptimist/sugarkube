# Headless sugarkube Provisioning

Bring a Raspberry Pi online without attaching a keyboard, monitor, or editing
repository files. The cloud-init snippets under `scripts/cloud-init/` inject
Wi-Fi credentials, Cloudflare tokens, and SSH keys on first boot so
`projects-compose` can pull `token.place` and `dspace` immediately.

## 1. Stage secrets safely

1. Copy the example configuration:
   ```bash
   cp scripts/cloud-init/secrets.env.example scripts/cloud-init/secrets.env
   ```
2. Edit `scripts/cloud-init/secrets.env` and replace the placeholders for Wi-Fi,
   Cloudflare integration (uncomment the token line when needed), and SSH
   access with values that match your environment.
3. Keep `secrets.env` untracked. The file is already ignored by git, and
   `scripts/scan-secrets.py` guards against accidental commits.

## 2. Customise user-data

The base `user-data.yaml` enables cloud-init modules required by the Pi image
workflow. Adjust the hostname, default user, or enable extra services by editing
`scripts/cloud-init/user-data.yaml`. Common tweaks include:

- Rotating the `chpasswd` section to set unique credentials
- Appending Wi-Fi credentials beyond the defaults for multi-network setups
- Adding additional SSH keys under the `ssh_authorized_keys` list

## 3. Apply configuration to media

After downloading an image with `install_sugarkube.sh`:

```bash
./scripts/install_sugarkube.sh --keep-xz
./scripts/flash_pi_media.sh --device /dev/sdx --yes
./scripts/cloud-init/init-env.sh /path/to/mounted/boot
```

`init-env.sh` copies `user-data.yaml`, expands secrets from `secrets.env`, and
sets up `network-config` so the Pi joins Wi-Fi on first boot. Rerun the script
any time secrets rotate; it overwrites previous values idempotently.

## 4. Codespaces friendly defaults

The same workflow works in GitHub Codespaces:

1. Mount the latest release with `./scripts/install_sugarkube.sh --dir /workspaces`.  
2. Attach removable media via the Codespaces USB bridge or forward the target to
   your local workstation.
3. Run `init-env.sh` to bake Wi-Fi and tokens into the mounted boot partition.

When the Pi powers on it fetches packages, registers with Cloudflare (when
configured), and exposes `token.place` and `dspace` without manual SSH steps.
