# Raspberry Pi Cluster Setup

This guide prepares a three-node Raspberry Pi 5 cluster for running [token.place](https://github.com/futuroptimist/token.place) and [dspace](https://github.com/democratizedspace/dspace) with k3s.

## Bill of Materials
- 3 × Raspberry Pi 5 (8 GB recommended)
- 3 × official Raspberry Pi M.2 HAT with NVMe SSDs
- 1 × triple Pi carrier plate (see [pi_cluster_carrier.md](pi_cluster_carrier.md))
- Power supplies, standoffs, and required cables
- Optional KVM for shared keyboard, video, and mouse access

## Workflow
1. **Download the OS image**
   - Grab `sugarkube.img.xz` from the latest [pi-image workflow run](https://github.com/futuroptimist/sugarkube/actions/workflows/pi-image.yml).
2. **Flash the SD card**
   - Use Raspberry Pi Imager.
   - Set hostname, enable SSH, and create a user with a strong password.
3. **Boot from SD**
   - Insert the card into a Pi on the carrier and power on with monitor or KVM attached.
4. **Clone to SSD**
   - Find the drive with `lsblk` then run `sudo rpi-clone sda -f`.
5. **Enable SSD boot**
   - `sudo raspi-config` → Advanced Options → Boot Order → `NVMe/USB`.
6. **Repeat for remaining Pis**
   - Install the image on the other nodes and confirm each boots from its SSD.
7. **Form the k3s cluster**
   - On the first Pi: `curl -sfL https://get.k3s.io | sh -`.
   - Note the node token in `/var/lib/rancher/k3s/server/node-token` and the IP.
   - On the other Pis: `curl -sfL https://get.k3s.io | K3S_URL=https://<control-ip>:6443 K3S_TOKEN=<token> sh -`.
8. **Deploy applications**
   - `git clone https://github.com/futuroptimist/token.place.git`
   - `git clone https://github.com/democratizedspace/dspace.git && cd dspace && git checkout v3`
   - Use `kubectl apply -f k8s/` or your preferred manifests to launch services.
9. **Expose with Cloudflare Tunnel**
   - Copy `docker-compose.cloudflared.yml` to `/opt/sugarkube/` on each node.
   - Store the tunnel token in `/opt/sugarkube/.cloudflared.env`.
   - Start the tunnel: `docker compose -f /opt/sugarkube/docker-compose.cloudflared.yml up -d`.
10. **Create environments**
    - Use k3s namespaces `dev`, `int`, and `prod` to separate deployments.
    - CI can promote images between namespaces after validation.
11. **Promote to production**
    - Tag a release in the integration namespace as golden and deploy that tag to `prod`.
    - Roll back by redeploying the previous known-good tag if needed.

For additional hardware and networking details see [network_setup.md](network_setup.md) and [pi_image_cloudflare.md](pi_image_cloudflare.md).
