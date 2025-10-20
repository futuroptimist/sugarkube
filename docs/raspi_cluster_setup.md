---
personas:
  - hardware
  - software
---

# Raspberry Pi Cluster Setup

This quick path keeps sugarkube's "syntactic sugar" promise: one command per node and sane
defaults. The detailed, step-by-step walkthrough now lives in
[raspi_cluster_setup_manual.md](raspi_cluster_setup_manual.md).

## Quick Start (same subnet; DHCP OK)

These steps assume all Pis sit on the same Layer 2 network where multicast (UDP port 5353) is
permitted for mDNS. Provide a unique registration token for each environment (`dev`, `int`,
`prod`) by exporting it before running the commands below (for example
`export SUGARKUBE_TOKEN_DEV=...`).

1. Power on a Raspberry Pi and sign in. The first `just up <env>` invocation on that environment
   bootstraps the control-plane:

   ```bash
   just up dev
   ```

2. Repeat `just up dev` on two more Pis. They discover the control-plane over mDNS, then join as
   agents. The server advertises itself as `<hostname>.local` and agents keep following it even if
   the DHCP lease changes.
3. For `int` and `prod`, rerun the same command with the matching environment. Each environment
   uses its own join token, hostname scope, and node labels, so clusters remain isolated even on the
   same switch.

### Handy helpers

- `just status` — display node readiness with wide columns (requires running on a server).
- `just kubeconfig` — copy `/etc/rancher/k3s/k3s.yaml` into `~/.kube/config` and chown it to the
  logged-in user.
- `just wipe` — remove k3s binaries, stop advertising the API over mDNS, and
  reset Avahi. Useful when repurposing a node.

## Configuration

All knobs are exported via the Justfile and can be overridden through environment variables:

- `SUGARKUBE_CLUSTER` — cluster name advertised over mDNS and stored in node labels. Defaults to
  `sugar`.
- `SUGARKUBE_SERVERS` — desired control-plane count per environment. Defaults to `1` (single server
  on SQLite). Set to `3` or more to enable embedded etcd.
- `K3S_CHANNEL` — release channel passed to the official `get.k3s.io` installer. Defaults to
  `stable`.
- `SUGARKUBE_TOKEN_DEV`, `SUGARKUBE_TOKEN_INT`, `SUGARKUBE_TOKEN_PROD` — preferred join tokens per
  environment. If unset, the automation falls back to `SUGARKUBE_TOKEN`.

Tokens gate node registration; rotate them when recycling hardware between environments.

## Networking Notes

- Each run installs Avahi (`avahi-daemon`, `avahi-utils`) and `libnss-mdns` so `.local` hostnames
  resolve correctly. The Just recipe also updates `/etc/nsswitch.conf` to include `mdns4_minimal
  [NOTFOUND=return]` before DNS.
- The control-plane publishes the Kubernetes API via Bonjour/mDNS as `_https._tcp` on port 6443
  with TXT records identifying the cluster, environment, and server role.
- Servers add their own `<hostname>.local` entry to the TLS Subject Alternative Names list so
  clients remain trusted after DHCP leases move.
- Agents initially target the discovered server's hostname, then rely on k3s' embedded
  client-side load balancer to learn about every server endpoint and fail over automatically.

## Topologies

- **Single server (default)** — when `SUGARKUBE_SERVERS=1`, k3s stays on SQLite and avoids
  `--cluster-init`. The server taints itself
  (`node-role.kubernetes.io/control-plane=true:NoSchedule`) so workloads land on agents by default.
- **Highly available control-plane** — set `SUGARKUBE_SERVERS` to `3` (or any odd number ≥3). The
  first server in that environment starts with `--cluster-init` to launch embedded etcd; subsequent
  servers join via the discovered hostname. Use SSDs instead of SD cards for the etcd datastore on
  Raspberry Pis to keep latency and write endurance in a safe range.

Need the full nuts-and-bolts procedure? Jump to
[raspi_cluster_setup_manual.md](raspi_cluster_setup_manual.md).
