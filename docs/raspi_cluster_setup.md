---
personas:
  - hardware
  - software
---

# Raspberry Pi Cluster Setup (Quick Start)

`sugarkube` makes forming a Raspberry Pi cluster almost effortless: once your Pis boot the standard image and share the same LAN, you can create a per-environment k3s cluster with a single command per node.

---

## Happy path: HA 3-server bootstrap

This is the streamlined sequence we recommend for almost every deployment. It assumes the Pis already boot Sugarkube's Raspberry Pi OS image, are reachable on the same L2 subnet, and can access the internet.

1. **Run `just up` to apply cgroup fixes (it will reboot)**

   ```bash
   just up dev
   ```

   The first execution installs prerequisites, checks whether the Linux memory cgroup controller is enabled, and updates `cmdline.txt` if Raspberry Pi OS disabled it. `just up` reboots automatically after writing the change.

2. **Log back in after the reboot and enable the HA control-plane**

   ```bash
   export SUGARKUBE_SERVERS=3
   just up dev
   ```

   Keeping the server count at an odd number (three is perfect for Raspberry Pi clusters) activates the embedded etcd datastore and advertises the node as a control-plane peer.

3. **Capture the join token**

   ```bash
   sudo cat /var/lib/rancher/k3s/server/node-token
   ```

   The long `K10…` string authorises additional nodes. Store it securely—any node that exports it can join the control-plane.

4. **Bring up the remaining control-plane nodes**

   Give each Pi a unique hostname (`sugarkube1`, `sugarkube2`, …) so their `.local` mDNS records do not collide, then repeat the bootstrap on the next two Pis:

   ```bash
   export SUGARKUBE_SERVERS=3
   export SUGARKUBE_TOKEN_DEV="K10abc123..."  # token gathered from sugarkube0
   just up dev
   ```

   Each run discovers the existing server over Bonjour/mDNS (`_https._tcp:6443`, `cluster=sugar`, `env=dev`, `role=server`) and joins the embedded etcd quorum.

5. **Join worker nodes (optional)**

   Additional Pis can remain as agents—just skip the `SUGARKUBE_SERVERS` export and provide the same token:

   ```bash
   export SUGARKUBE_TOKEN_DEV="K10abc123..."
   just up dev
   ```

6. **Switch environments when needed**

   Each environment (`dev`, `int`, `prod`) maintains its own token and mDNS advertisement:

   ```bash
   just up int
   just up prod
   ```

   You can even run multiple environments on the same LAN simultaneously as long as they use different tokens.

---

## Conceptual Overview

K3s, the lightweight Kubernetes used by Sugarkube, organizes nodes into **servers** (control-plane) and **agents** (workers). Each cluster environment (like `dev`, `int`, or `prod`) needs a **join token** that authorizes new nodes to join its control-plane.

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

### After bootstrap

- Check node readiness from any cluster member:
  ```bash
  just status
  ```

- Export an environment-scoped kubeconfig locally:
  ```bash
  just kubeconfig env=dev
  ```
  The file lands in `~/.kube/config` with the context renamed to `sugar-dev` and the `.local` hostname preserved for TLS.

- To manage the cluster from your workstation, copy that kubeconfig and adjust credentials as outlined in [Manage from a workstation](./network_setup.md#manage-from-a-workstation).

- When you need to reset a node, run:
  ```bash
  just wipe
  ```
  This runs the official uninstall scripts, drops its Avahi service file, and restarts the daemon.

Need deeper operational playbooks? Continue with [docs/runbook.md](./runbook.md). When the control plane is steady, bootstrap GitOps with [`scripts/flux-bootstrap.sh`](../scripts/flux-bootstrap.sh) or `just flux-bootstrap env=dev`.

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
