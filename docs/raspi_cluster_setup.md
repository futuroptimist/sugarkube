---
personas:
  - hardware
  - software
---

# Raspberry Pi Cluster Setup

Sugarkube keeps the cluster path sweet: every Pi gets a single command and the
recipes handle discovery, mDNS hostnames, and kubeconfig hand-offs.

## Quick Start (same subnet; DHCP OK)

1. Export unique registration tokens per environment (strong random strings):
   ```bash
   export SUGARKUBE_TOKEN_DEV=...
   export SUGARKUBE_TOKEN_INT=...
   export SUGARKUBE_TOKEN_PROD=...
   # Optional: fall back token when per-env secrets are unset
   export SUGARKUBE_TOKEN=...
   ```
2. Plug three Raspberry Pi nodes into the same L2 network (multicast + UDP 5353
   must be allowed). Boot each Pi with Sugarkube's Raspberry Pi OS image.
3. On the first Pi for an environment, run:
   ```bash
   just up dev
   ```
   The `up` recipe installs Avahi + libnss-mdns, bootstraps a k3s server, and
   advertises `_https._tcp:6443` via Bonjour/mDNS using the Pi's `.local`
   hostname and TLS SANs so DHCP address changes remain safe.
4. On the next two Pis for the same environment, run the exact same command:
   ```bash
   just up dev
   ```
   Each agent discovers the server over mDNS, joins with the environment token,
   and learns the other control-plane endpoints via k3s' embedded client-side
   load balancer. Repeat for `int` and `prod` to keep clusters separated by
   deterministic environment labels.
5. Inspect the cluster from any node:
   ```bash
   just status
   ```
6. On a server, copy the kubeconfig for remote use:
   ```bash
   just kubeconfig
   ```
7. Need to reset a node? Remove k3s and the Bonjour advertisement:
   ```bash
   just wipe
   ```

## Configuration

All values can be overridden via environment variables before running `just up`:

- `SUGARKUBE_CLUSTER` (default `sugar`): logical name included in mDNS TXT
  records and node labels.
- `SUGARKUBE_SERVERS` (default `1`): desired control-plane count per
  environment. `1` keeps the datastore on SQLite; set ≥`3` to enable the
  embedded etcd HA flow.
- `K3S_CHANNEL` (default `stable`): release channel consumed by `get.k3s.io`.
- `SUGARKUBE_TOKEN_DEV`, `SUGARKUBE_TOKEN_INT`, `SUGARKUBE_TOKEN_PROD`: per-env
  registration tokens. `SUGARKUBE_TOKEN` acts as a fallback when a
  per-environment secret is unset.

`just up` exports `SUGARKUBE_ENV` automatically from the recipe parameter.

## Networking Notes

- Avahi and `libnss-mdns` are installed automatically; `.local` hostnames resolve
  via NSS with `mdns4_minimal` ahead of unicast DNS.
- UDP 5353 must pass on the subnet. Servers broadcast the Kubernetes API as
  `_https._tcp` with TXT records marking the cluster and environment so agents
  only join the intended control plane.
- Agents seed from one `.local` hostname and then rely on the client-side load
  balancer baked into k3s to discover additional servers and survive IP churn.
- Control-plane nodes are tainted with
  `node-role.kubernetes.io/control-plane=true:NoSchedule` to keep workloads on
  the agents by default.

## Topologies

- **Single server (default)**: `SUGARKUBE_SERVERS=1` keeps the datastore on
  SQLite—no `--cluster-init` is used. Ideal for lightweight edge clusters.
- **Embedded etcd HA**: Set `SUGARKUBE_SERVERS=3` (or higher odd counts). The
  first server in an environment bootstraps with `--cluster-init`; subsequent
  servers join via the discovered peer. Use SSD-backed storage on Raspberry Pis
  to meet k3s' IO guidance for etcd.

## Need the manual steps?

When you want the long-form walkthrough—from flashing SD cards to manual join
commands—open [raspi_cluster_setup_manual.md](raspi_cluster_setup_manual.md).

