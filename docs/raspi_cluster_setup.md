# Raspberry Pi Cluster Setup

This expanded guide walks through building a three-node Raspberry Pi 5 cluster and installing k3s so you can run [token.place](https://github.com/futuroptimist/token.place) and [dspace](https://github.com/democratizedspace/dspace). It assumes basic familiarity with the Linux command line.

## Bill of Materials
- 3 × Raspberry Pi 5 (8 GB recommended)
- 3 × official Raspberry Pi M.2 HAT with NVMe SSDs
- 1 × triple Pi carrier plate (see [pi_cluster_carrier.md](pi_cluster_carrier.md))
- Power supplies, standoffs, and required cables
- MicroSD card for each node (8 GB minimum)
- Optional KVM for shared keyboard, video, and mouse access

## Prerequisites
- A workstation with [Raspberry Pi Imager](https://www.raspberrypi.com/software/) installed
- Basic networking knowledge. Review [network_setup.md](network_setup.md) for static IPs
- SSH client (e.g. `ssh` on macOS/Linux or PuTTY on Windows)
- Internet connection to download images and packages

## 1. Prepare the OS image
1. Run `scripts/download_pi_image.sh` to fetch `sugarkube.img.xz` from the latest
   [pi-image workflow run](https://github.com/futuroptimist/sugarkube/actions/workflows/pi-image.yml),
   or download it manually from the Actions tab.

   Alternatively, build locally:
   - Linux/macOS: `./scripts/build_pi_image.sh`
   - Windows (PowerShell):
     ```powershell
     # Optional: increase WSL/WSL2 resources for Docker Desktop (recommended)
     # File: C:\Users\<you>\.wslconfig
     # [wsl2]
     # memory=64GB
     # processors=24
     # swap=16GB
     # localhostForwarding=true
     # vmIdleTimeout=7200
     # Then apply and rerun build:
     wsl --shutdown

     # Build the image
     powershell -ExecutionPolicy Bypass -File .\scripts\build_pi_image.ps1
     ```
     Notes:
     - Setting `localhostForwarding=true` forwards WSL ports to Windows
     - Requires Docker Desktop running and Git for Windows installed
     - The script auto-falls back to a Dockerized build and sets up binfmt/qemu
     - Expect 45–120 minutes on Windows; ensure ≥30 GB free disk
2. Verify the checksum: `sha256sum -c sugarkube.img.xz.sha256`
3. Flash the image to a microSD card using Raspberry Pi Imager
   - Set a unique hostname (e.g., `sugar-01`, `sugar-02`, `sugar-03`), enable SSH, and create a user with a strong password
   - Use <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>X</kbd> to enter advanced options and configure WiFi SSID, password, and locale
   - The same image can be reused for all nodes

## 2. Boot and clone to SSD
1. Insert the card into a Pi on the carrier and power on with monitor or KVM attached
2. Verify the NVMe drive shows up: `lsblk`
3. Install rpi-clone if missing: `sudo apt install -y rpi-clone`
4. Clone the SD card to the SSD: `sudo rpi-clone sda -f`
5. Shut down the Pi, remove the SD card, and power back on to confirm the SSD boots

## 3. Enable SSD boot (if needed)
1. Run `sudo raspi-config` → Advanced Options → Boot Order → `NVMe/USB`
2. Reboot and confirm `lsblk` shows the root filesystem on the SSD

## 4. Repeat for remaining Pis
Follow the steps above for each node so every Pi boots from its own SSD.

## 5. Form the k3s cluster
1. On the first Pi (control plane):
   ```bash
   curl -sfL https://get.k3s.io | sh -
   ```
2. Note the node token in `/var/lib/rancher/k3s/server/node-token` and its IP address
3. On each additional Pi, join the cluster:
   ```bash
   curl -sfL https://get.k3s.io | \
   K3S_URL=https://<control-ip>:6443 K3S_TOKEN=<token> sh -
   ```
4. Check that all nodes are ready:
   ```bash
   sudo kubectl get nodes
   ```
5. (Optional) Copy `/etc/rancher/k3s/k3s.yaml` to your workstation for remote
   `kubectl` access.

## 6. Deploy applications
1. Clone the repositories:
   ```bash
   git clone https://github.com/futuroptimist/token.place.git
   git clone https://github.com/democratizedspace/dspace.git
   cd dspace && git checkout v3
   ```
2. Apply Kubernetes manifests or Helm charts to launch services:
   ```bash
   kubectl apply -f k8s/
   ```

## 7. Expose with Cloudflare Tunnel
1. Copy `docker-compose.cloudflared.yml` to `/opt/sugarkube/` on each node
2. Store the tunnel token in `/opt/sugarkube/.cloudflared.env`
3. Start the tunnel:
   ```bash
   docker compose -f /opt/sugarkube/docker-compose.cloudflared.yml up -d
   ```

## 8. Create environments
Use k3s namespaces `dev`, `int`, and `prod` to separate deployments. CI can promote images between namespaces after validation.

## 9. Promote to production
Tag a release in the integration namespace as golden and deploy that tag to `prod`. Roll back by redeploying the previous known-good tag if needed.

## Next steps
Explore [network_setup.md](network_setup.md) for networking tips and [pi_image_cloudflare.md](pi_image_cloudflare.md) for details on exposing services securely.
