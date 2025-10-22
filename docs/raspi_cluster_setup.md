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

   On the first Pi (name it `sugarkube0` so its `.local` hostname is predictable) for an environment (defaults to `dev`):

   ```bash
   just up dev
   ```

   This installs Avahi/libnss-mdns, bootstraps a k3s server, publishes the API as
   `_https._tcp:6443` via Bonjour/mDNS with `cluster=sugar` and `env=dev` TXT records,
   and taints itself (`node-role.kubernetes.io/control-plane=true:NoSchedule`) so workloads prefer agents.

   > **HA choice**
   >
   > - `SUGARKUBE_SERVERS=1` (default) initializes the embedded SQLite datastore. Later nodes join as agents unless you promote them manually.
   > - `SUGARKUBE_SERVERS>=3` (recommended for HA) makes the very first `just up` run `k3s server --cluster-init` with the embedded etcd datastore. Subsequent servers join over mDNS and form quorum automatically.
   >
   > Decide before the first bootstrap. If you want HA, run `export SUGARKUBE_SERVERS=3` **before** the initial `just up dev` so every server advertises correctly via mDNS.

   When it finishes, capture its join token:

   ```bash
   sudo cat /var/lib/rancher/k3s/server/node-token
   ```

   Copy that long `K10…` string somewhere safe.

3. **Join worker or additional server nodes**

   Keep every Pi on the same L2 subnet so `.local` hostnames resolve over mDNS. Name the second and third nodes `sugarkube1` and `sugarkube2`, copy the token you gathered from `sugarkube0`, and then run:

   ```bash
   export SUGARKUBE_TOKEN_DEV="K10abc123..."
   just up dev
   ```

   With the default single-server flow they become agents. When `SUGARKUBE_SERVERS=3`, each additional run starts a control-plane server, discovers peers via mDNS TXT records, and joins the embedded etcd cluster with the shared token.

4. **Switch environments easily**

   Each environment (`dev`, `int`, `prod`) maintains its own token and mDNS advertisement:

   ```bash
   just up int
   just up prod
   ```

   You can even run multiple environments on the same LAN simultaneously as long as they use different tokens.

5. **Wipe a node clean**

   ```bash
   just wipe
   ```

   This runs the official uninstall scripts, drops its Avahi service file, and restarts the daemon.

### After bootstrap

- **Confirm node health** from any server:

  ```bash
  just status
  ```

- **Export kubeconfig** on a node so the context becomes `sugar-dev` (or `int`/`prod`):

  ```bash
  just kubeconfig
  ```

  The file lands in `~/.kube/config` with the `.local` control-plane hostname already pinned. Pass `env=int` or `env=prod` if you are exporting another environment. To manage the cluster from another machine, copy that file over and follow [Manage from a workstation](network_setup.md#manage-from-a-workstation).

- **Next steps**: deeper recovery procedures live in the [Sugarkube runbook](runbook.md#validation-commands). When you are ready to layer GitOps, see [`scripts/flux-bootstrap.sh`](../scripts/flux-bootstrap.sh) or run `just flux-bootstrap env=dev` after the control plane is healthy.

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

  `just up` now reads the generated token from `/var/lib/rancher/k3s/server/node-token`
  (or `/boot/sugarkube-node-token`) when bootstrapping a single-server cluster, so you
  should only see this error when orchestrating multi-server or agent joins. Export the
  appropriate environment variable with the control-plane token before retrying.

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
