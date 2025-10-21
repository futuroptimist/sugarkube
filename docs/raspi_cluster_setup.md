---
personas:
  - hardware
  - software
---

# Raspberry Pi Cluster Setup (Quick Start)

`sugarkube` makes forming a Raspberry Pi cluster almost effortless: once your Pis boot the standard image and share the same LAN, you can create a per-environment k3s cluster with a single command per node.

---

## Conceptual Overview

K3s, the lightweight Kubernetes used by Sugarkube, organizes nodes into **servers** (control-plane) and **agents** (workers).
Each cluster environment (like `dev`, `int`, or `prod`) needs a **join token** that authorizes new nodes to join its control-plane.

When the first node starts `k3s` as a server, it automatically creates a secret file at:

```
/var/lib/rancher/k3s/server/node-token
```

That token is what other nodes must present to join. Sugarkube never invents its own tokens—it just expects you to export them before you run `just up`.

The pattern is:

| Environment | Env var read by `just up` | Example |
|--------------|---------------------------|----------|
| dev | `SUGARKUBE_TOKEN_DEV` | export SUGARKUBE_TOKEN_DEV="K10abcdef…" |
| int | `SUGARKUBE_TOKEN_INT` | export SUGARKUBE_TOKEN_INT="K10ghijk…" |
| prod | `SUGARKUBE_TOKEN_PROD` | export SUGARKUBE_TOKEN_PROD="K10lmno…" |
| fallback | `SUGARKUBE_TOKEN` | used if no env-specific token is set |

---

## Quick Start (same subnet, DHCP friendly)

### Before you begin: enable memory cgroups

`k3s` expects the Linux memory cgroup controller to be active. Raspberry Pi OS disables it by
default, so update the boot configuration once per device before running `just up`:

```bash
if [[ -f /boot/firmware/cmdline.txt ]]; then
  sudo sed -i 's/$/ cgroup_memory=1 cgroup_enable=memory/' /boot/firmware/cmdline.txt
else
  sudo sed -i 's/$/ cgroup_memory=1 cgroup_enable=memory/' /boot/cmdline.txt
fi
sudo reboot
```

After the reboot, rerun the helper to confirm the controller is available:

```bash
./scripts/check_memory_cgroup.sh || true
```

1. **Ensure network reachability**

   - All Pis must be on the same L2 subnet with multicast (UDP 5353) allowed.
   - Each Pi should be able to reach the internet.

2. **Bootstrap the first control-plane node**

   On the first Pi for an environment (defaults to `dev`):

   ```bash
   just up dev
   ```

   This installs Avahi/libnss-mdns, bootstraps a k3s server, publishes the API as
   `_https._tcp:6443` via Bonjour/mDNS with `cluster=sugar` and `env=dev` TXT records,
   and taints itself (`node-role.kubernetes.io/control-plane=true:NoSchedule`) so workloads prefer agents.

   When it finishes, capture its join token:

   ```bash
   sudo cat /var/lib/rancher/k3s/server/node-token
   ```

   Copy that long `K10…` string somewhere safe.

3. **Join worker or additional server nodes**

   On each additional Pi you want in the same environment, export the token you copied:

   ```bash
   export SUGARKUBE_TOKEN_DEV="K10abc123..."
   just up dev
   ```

   These nodes discover the control-plane over mDNS, join using that token, and then rely on k3s’ built-in load balancer for ongoing discovery.

4. **Switch environments easily**

   Each environment (`dev`, `int`, `prod`) maintains its own token and mDNS advertisement:

   ```bash
   just up int
   just up prod
   ```

   You can even run multiple environments on the same LAN simultaneously as long as they use different tokens.

5. **Manage and inspect**

   - Export kubeconfig for a workstation:
     ```bash
     just kubeconfig
     ```
     The file is written to `~/.kube/config` and already includes the `.local` hostname in the TLS SAN, so DHCP IP churn is safe.

   - Check cluster status:
     ```bash
     just status
     ```

   - Wipe a node clean:
     ```bash
     just wipe
     ```
     This runs the official uninstall scripts, drops its Avahi service file, and restarts the daemon.

---

## Configuration Knobs

You can override defaults inline (e.g. `SUGARKUBE_SERVERS=3 just up prod`) or export them in your shell profile.

| Variable | Default | Purpose |
|-----------|----------|----------|
| `SUGARKUBE_CLUSTER` | `sugar` | Logical cluster prefix advertised via mDNS |
| `SUGARKUBE_SERVERS` | `1` | Desired control-plane count per environment |
| `K3S_CHANNEL` | `stable` | Channel for the official k3s install script |
| `SUGARKUBE_TOKEN_DEV` / `INT` / `PROD` | _none_ | Environment-specific join tokens (see above) |
| `SUGARKUBE_TOKEN` | _none_ | Fallback token if no per-env variant is set |

### Generating Tokens Manually
If you ever need to regenerate a token, run this on a control-plane node:
```bash
sudo cat /var/lib/rancher/k3s/server/node-token
```
or, if that file is missing, reinstall the server (`just up dev` on a fresh node) and grab the new token.

---

## Networking Notes

- **mDNS**: Avahi (`avahi-daemon` + `avahi-utils`) and `libnss-mdns` enable `.local` hostname resolution.
  The `prereqs` recipe ensures `/etc/nsswitch.conf` includes
  `mdns4_minimal [NOTFOUND=return] dns mdns4`.

- **Service advertisement**:
  Servers broadcast the Kubernetes API as `_https._tcp` on port `6443` with TXT records tagging cluster (`cluster=<name>`), environment (`env=<env>`), and role (`role=server`).
  Agents use these `.local` hostnames to locate the control-plane automatically.

- **Multicast**:
  Keep UDP 5353 open within the subnet. `.local` is reserved for link-local mDNS per [RFC 6762](https://www.rfc-editor.org/rfc/rfc6762).

---

## Typical Topologies

- **Single-server (default)** —
  The first node bootstraps k3s with the built-in SQLite datastore.
  Agents join it directly and workloads run on agents.

- **High-availability (HA)** —
  Set `SUGARKUBE_SERVERS>=3` before bring-up.
  The first server starts etcd with `--cluster-init`; subsequent servers detect peers via mDNS and join over `https://<peer>:6443`.
  Use NVMe or SSD storage for HA; SD cards aren’t durable enough for etcd writes.

---

## Troubleshooting

- **Error: `SUGARKUBE_TOKEN (or per-env variant) required`**

  You tried to run `just up` on a node without exporting the token.
  Retrieve it from the control-plane (`/var/lib/rancher/k3s/server/node-token`) and set the appropriate environment variable before retrying.

- **Cluster discovery fails**

  - Confirm multicast (UDP 5353) is allowed.
  - Verify `avahi-daemon` is running (`sudo systemctl status avahi-daemon`).
  - Check that `/etc/nsswitch.conf` contains `mdns4_minimal`.

- **Reset everything**

  ```bash
  just wipe
  sudo reboot
  ```

---

Once all three default nodes for an environment report `Ready`, proceed to the deployment playbooks (`token.place`, `dspace`, etc.) as usual.

> For a step-by-step deep dive, see
> [raspi_cluster_setup_manual.md](raspi_cluster_setup_manual.md).

---
