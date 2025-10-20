---
personas:
  - hardware
  - software
---

# Raspberry Pi Cluster Setup

Sugarkube promises syntactic sugar, so the high-level path stays short. Dive into
[`raspi_cluster_setup_manual.md`](raspi_cluster_setup_manual.md) when you need the
full step-by-step playbook for imaging media, cloning to NVMe, and hand-running
k3s commands.

## Quick Start (same subnet; DHCP OK)

> All nodes must share the same L2 network segment with multicast enabled so mDNS
> (`_https._tcp` on UDP 5353) works. Run these commands over SSH from each Pi once
> the sugarkube repo is cloned locally.

1. Pick an environment label—`dev`, `int`, or `prod`—and export a join token for
   that environment on every Pi. The first node to run `just up <env>` becomes the
   control-plane server; the next two become agents.
   ```bash
   cd ~/sugarkube
   export SUGARKUBE_TOKEN_DEV='change-me-dev'   # or INT/PROD as appropriate
   just up dev
   ```
2. Repeat on two more Pis to form the default three-node cluster. The helper:
   - Installs Avahi + libnss-mdns so `.local` hostnames resolve via mDNS.
   - Discovers an existing `${SUGARKUBE_CLUSTER}/${SUGARKUBE_ENV}` API over mDNS
     and joins it automatically.
   - Boots the first server on SQLite by default, taints it `NoSchedule`, and labels
     every node with `sugarkube.cluster` and `sugarkube.env`.
3. Check cluster health from any node:
   ```bash
   just status
   ```
4. On a server, copy the kubeconfig for workstation use:
   ```bash
   just kubeconfig
   ```
5. Need a fresh start? Run `just wipe` on the node you want to reset. This removes
   k3s, tears down the Avahi advertisement, and restarts `avahi-daemon`.

Repeat the same flow for `int` and `prod` environments. Each label seeds a distinct
cluster even on the same LAN because tokens and mDNS TXT markers stay scoped per
environment.

## Configuration

Override these environment variables as needed:

- `SUGARKUBE_CLUSTER` (default `sugar`): logical cluster prefix shared across
  environments.
- `SUGARKUBE_SERVERS` (default `1`): desired control-plane count per
  environment. `1` keeps SQLite; three or more triggers embedded etcd.
- `K3S_CHANNEL` (default `stable`): release channel passed to the
  `get.k3s.io` installer.
- `SUGARKUBE_TOKEN_{DEV,INT,PROD}`: per-environment join tokens. When unset the
  helper falls back to `SUGARKUBE_TOKEN`.

Set these inline with the `just` command or export them in `/etc/environment`
when you want persistent defaults. Tokens gate registration, so generate
distinct secrets per environment (for example with `openssl rand -hex 16`).

## Networking Notes

Avahi handles mDNS advertisements while `libnss-mdns` makes `.local` names resolve
through NSS using the `mdns4_minimal` plugin. Keep UDP 5353 unblocked so discovery
works. Servers publish themselves as `_https._tcp` port 6443 with TXT markers that
include `cluster=<name>`, `env=<label>`, and `role=server`. Agents seed from the
first discovered server hostname and then rely on K3s's embedded client-side load
balancer to learn every control-plane endpoint, so DHCP address churn is safe as
long as TLS SANs cover the `.local` names.

## Topologies

The default `SUGARKUBE_SERVERS=1` path brings up a single server backed by
SQLite—no `--cluster-init`—which is ideal for quick dev clusters. When you need a
high-availability control plane, set `SUGARKUBE_SERVERS=3` (or more) and run the
same `just up <env>` command on each server-class Pi. The first node bootstraps
embedded etcd with `--cluster-init`; subsequent servers join via the advertised
`.local` hostname. Use NVMe SSDs (not SD cards) for etcd durability per the K3s
requirements.

For wiring diagrams, inventory, and manual recovery steps, continue to the
[manual guide](raspi_cluster_setup_manual.md).
