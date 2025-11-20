---
personas:
  - hardware
  - software
---

# Raspberry Pi Cluster Setup (Manual)

**📚 Part 1 of 3** in the [Raspberry Pi cluster series](index.md#raspberry-pi-cluster-series)
- **Next:** [Part 2 - Quick-Start Setup](raspi_cluster_setup.md)
- **Then:** [Part 3 - Operations & Helm](raspi_cluster_operations.md)

> Looking for the condensed bring-up path? Start with
> [raspi_cluster_setup.md](raspi_cluster_setup.md) for the one-command `just up <env>` flow
> and hop back here when you need the full manual checklist.

## What the quick start automates

`raspi_cluster_setup.md` collapses the longer manual procedure into two `just up <env>`
runs per node. The new helper recipes introduced alongside this cleanup further
reduce typing:

| Manual checklist task | Steps in this document | Quick-start equivalent | Savings | Approx. commands / time saved |
|-----------------------|------------------------|------------------------|---------|------------------------------|
| §5.1–§5.4: install k3s, capture the token, rehearse joins, and run `make cluster-up` | 7 distinct commands plus environment exports | Two invocations of `just up dev` (or `just ha3 env=dev`) plus `just cat-node-token` | ~70% fewer commands and zero manual curl scripts | ~7 commands trimmed to 3 (≈55–70% faster) |
| Passing tokens between shells | Copy `/var/lib/rancher/k3s/server/node-token`, export `SUGARKUBE_TOKEN_<ENV>` | `just cat-node-token` prints the value via `sudo`; export once before rerunning `just up` | Removes two manual steps per node | 2 exports collapsed into a single copy/paste |
| Capturing debug logs | Run `SAVE_DEBUG_LOGS=1 just up dev`, find the sanitized file manually | `just save-logs env=dev` wraps the export and prints the output path automatically | Eliminates three environment edits | Cuts three edits plus the file lookup |
| Enabling HA | `export SUGARKUBE_SERVERS=3` before each command | `just ha3 env=dev` sets the env var and executes `just up` in one go | Removes repeated exports across both runs | 2 exports replaced by one reusable recipe |

Use this manual as the full reference when you need to reason about every moving
part (pi-image builds, SSD migration, or bespoke rehearsals). Otherwise, stick to
the quick start plus the new day-two guide so operators only type the minimum
necessary commands.

This expanded guide walks through building a three-node Raspberry Pi 5 cluster and installing k3s
so you can run [token.place](https://github.com/futuroptimist/token.place) and
[dspace](https://github.com/democratizedspace/dspace). It assumes basic familiarity with the
Linux command line.

## Bill of Materials
- 3 × Raspberry Pi 5 (8 GB recommended)
- 3 × official Raspberry Pi M.2 HAT with NVMe SSDs
- 1 × triple Pi carrier plate (see [pi_cluster_carrier.md](pi_cluster_carrier.md))
- Active airflow. If you skip the carrier stack's built-in fan, position a small desk fan so the
  boards stay below 60 °C—thermal throttling starts at 80 °C and spot-checks fail above 60 °C.
- Power supplies, standoffs, and required cables
- MicroSD card for each node (8 GB minimum)
- Optional KVM for shared keyboard, video, and mouse access

## Prerequisites
- A workstation with [Raspberry Pi Imager](https://www.raspberrypi.com/software/) installed
- Basic networking knowledge. Review [network_setup.md](network_setup.md) for static IPs
- SSH client (e.g. `ssh` on macOS/Linux or PuTTY on Windows)
- Internet connection to download images and packages

## Fast path: bootstrap all three nodes automatically
1. Copy [`samples/pi-cluster/three-node.toml`](../samples/pi-cluster/three-node.toml) to a
   writable directory and edit it to match your hardware:
   - Update `device` entries with the removable drives for each Pi.
   - Set `hostname`, Wi-Fi credentials, and SSH keys once and reuse them across nodes.
   - Adjust the `cluster.join` section with your control-plane hostname or IPs.
   - The sample now ships with `[image.workflow] trigger = true`, so the helper automatically
     dispatches the `pi-image` workflow, waits for the run to finish, and downloads the artifact
     without leaving the terminal. Disable it (`trigger = false`) when you already have a fresh
     image cached locally.
2. Preview the workflow without touching hardware:
   ```bash
   python -m sugarkube_toolkit pi cluster --config ./cluster.toml --dry-run
   ```
   The helper prints the commands it would execute (download, flash, join) so you can validate
   device paths and arguments before proceeding.
3. Drop `--dry-run` when you're ready:
   ```bash
   python -m sugarkube_toolkit pi cluster --config ./cluster.toml
   ```
   The automation dispatches the `pi-image` workflow (when `image.workflow.trigger` is enabled),
   waits for the build to complete, downloads the artifact (or reuses an existing
   `install_sugarkube_image.sh` cache), flashes each SD card via `flash_pi_media_report.py`, copies
   per-node cloud-init overrides that inject the hostnames and Wi-Fi credentials you supplied, and
   finally runs `pi_multi_node_join_rehearsal.py --apply` to bring the workers online. Use
   `just cluster-bootstrap CLUSTER_BOOTSTRAP_ARGS="--config ./cluster.toml"` when you prefer Just
   recipes.

Skip to [§5](#5-form-the-k3s-cluster) after the helper completes—the control-plane and workers
will already share the same image, hostname overrides, and join token.

## 1. Prepare the OS image
1. Trigger the build in GitHub:
   - If you used the `[image.workflow] trigger = true` default, the cluster bootstrapper already
     dispatched the workflow and downloaded the artifact for you—skip to step 2.
   - Otherwise open [Actions → pi-image → Run workflow][pi-image], enable **token.place** and
     **dspace** if you want those repos baked in, then download `sugarkube.img.xz` with
     `scripts/download_pi_image.sh` or from the workflow run page.

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
     - Requires Docker Desktop running and Git for Windows installed
     - The script auto-falls back to a Dockerized build and sets up binfmt/qemu
     - Expect 45–120 minutes on Windows; ensure ≥30 GB free disk
2. Verify the checksum: `sha256sum -c sugarkube.img.xz.sha256`
3. Flash the image to a microSD card using Raspberry Pi Imager
   - Set a unique hostname (e.g., `sugar-01`, `sugar-02`, `sugar-03`), enable SSH, and create a user
     with a strong password.
   - Press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>X</kbd> to open advanced options and configure the
     WiFi SSID, password, and locale.
   - The same image can be reused for all nodes.

## 2. Boot and clone to SSD
1. Insert the card into a Pi on the carrier and power on with monitor or KVM attached
2. Verify the NVMe drive shows up: `lsblk`
3. Preview the clone plan: `sudo ./scripts/ssd_clone.py --target /dev/sda --dry-run`
   (replace `/dev/sda` with your NVMe target).
4. Execute the clone once you're comfortable with the plan: `sudo ./scripts/ssd_clone.py --target /dev/sda`
   - If power hiccups or cables disconnect mid-transfer, rerun with `--resume` to continue
     from the last completed step without restarting the whole clone.
5. Shut down the Pi, remove the SD card, and power back on to confirm the SSD boots.

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
2. Note the node token in `/var/lib/rancher/k3s/server/node-token` (it is also copied
   to `/boot/sugarkube-node-token`) and the Pi's IP address
3. Before inviting other nodes, run a rehearsal from your workstation to confirm the token is
   mirrored and workers can reach the API:
   ```bash
   make rehearse-join REHEARSAL_ARGS="sugar-control.local --agents sugar-worker-a.local sugar-worker-b.local"
   ```
   The helper prints the join command template and checks each worker for network reachability,
   existing `k3s-agent` state, and leftover registration files.
4. Happy path for a three-node cluster (one control-plane plus two workers):
   ```bash
   make cluster-up CLUSTER_ARGS="sugar-control.local --agents sugar-worker-a.local sugar-worker-b.local --apply --apply-wait"
   ```
   The automation aborts if a worker fails the preflight, executes the join command remotely when
   the checks pass, and waits up to five minutes for every node to report `Ready`. Override the
   timeout with `--apply-wait-timeout` when slower networks need more time.
5. Prefer a manual join? Run the command emitted during the rehearsal on each worker:
   ```bash
   curl -sfL https://get.k3s.io | \
   K3S_URL=https://<control-ip>:6443 K3S_TOKEN=<token> sh -
   ```
6. Check that all nodes are ready:
   ```bash
   sudo kubectl get nodes
   ```
7. (Optional) Copy `/boot/sugarkube-kubeconfig-full` to your workstation for remote
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
1. Edit `/opt/sugarkube/docker-compose.cloudflared.yml` if needed (cloud-init installs it)
2. Store the tunnel token in `/opt/sugarkube/.cloudflared.env`
3. Start the tunnel service:
   ```bash
   sudo systemctl enable --now cloudflared-compose
   ```
4. Confirm the service is active:
   ```bash
   systemctl status cloudflared-compose --no-pager
   ```

## 8. Create environments
Use k3s namespaces `dev`, `int`, and `prod` to separate deployments.
CI can promote images between namespaces after validation.

## 9. Promote to production
Tag a release in the integration namespace as golden and deploy that tag to `prod`.
Roll back by redeploying the previous known-good tag if needed.

## Exercises

Practice what you've learned with these hands-on tasks:

1. **Compare automation coverage:** Review the table in §"What the quick start automates" and identify which manual steps from §5 (Form the k3s cluster) are eliminated by `just up dev`. Count how many shell commands you avoid by using the quick-start flow.

2. **Manual token capture:** On your control-plane node, manually retrieve the join token using `sudo cat /var/lib/rancher/k3s/server/node-token` and compare it to the output of `just cat-node-token`. Verify they match character-for-character.

3. **Rehearse before joining:** Before adding a new worker node, run the rehearsal command from §5.3 to check network reachability and ensure the control plane is advertising its mDNS service. Record any warnings or errors for troubleshooting.

4. **Clone validation:** After completing an SSD clone in §2, run `sudo ./scripts/ssd_clone.py --target /dev/sda --dry-run` again (replace `/dev/sda` with your target) and observe that the script reports the clone is already complete.

5. **Environment separation:** Create a second environment by exporting `SUGARKUBE_TOKEN_INT` with a new token and running `just up int` on a separate Pi. Verify that `dev` and `int` clusters can coexist on the same LAN with `kubectl get nodes` showing different members.

## Next steps
Explore [network_setup.md](network_setup.md) for networking tips and
[pi_image_cloudflare.md](pi_image_cloudflare.md) for details on exposing services securely.

[pi-image]: https://github.com/futuroptimist/sugarkube/actions/workflows/pi-image.yml
