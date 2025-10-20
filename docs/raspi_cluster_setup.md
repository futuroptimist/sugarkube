---
personas:
  - hardware
  - software
---

# Raspberry Pi Cluster Setup (Quick Start)

`sugarkube` now promises "syntactic sugar" for Raspberry Pi clusters: once your Pis boot
the standard image and share the same LAN, you can form per-environment k3s clusters with a
single command per node.

## Quick start (same subnet, DHCP friendly)

1. Make sure each Pi is on the same L2 subnet with multicast allowed (UDP 5353 for mDNS) and can
   reach the internet.
2. On the first Pi for an environment (defaults to `dev`), run:
   ```bash
   just up dev
   ```
   The node installs Avahi/libnss-mdns, bootstraps a k3s server, publishes the API as
   `_https._tcp:6443` via Bonjour/mDNS with `cluster=sugar` and `env=dev` TXT records, and taints
   itself (`node-role.kubernetes.io/control-plane=true:NoSchedule`) so workloads prefer agents.
3. Repeat `just up dev` on two more Pis to add agents. They discover the control-plane via mDNS,
   join using the `SUGARKUBE_TOKEN_DEV` token, and let k3s' embedded client load balancer discover
   additional servers automatically.
4. Switch environments by changing the recipe argument:
   ```bash
   just up int
   just up prod
   ```
   Each environment has its own join token and DNS-SD advertisement, so dev/int/prod clusters can
   coexist on the same network without IP gymnastics.
5. On any server node, export kubeconfig for a workstation:
   ```bash
   just kubeconfig
   ```
   The file ends up in `~/.kube/config` with the server's `.local` hostname already present in the
   TLS SAN list, so DHCP IP churn is safe.
6. Inspect the cluster at any time:
   ```bash
   just status
   ```
7. Need a clean slate? Use:
   ```bash
   just wipe
   ```
   The helper runs the official uninstall scripts, drops the Avahi service file, and restarts the
   daemon.

Once the three default nodes per environment are `Ready`, follow the deployment playbooks (token.place
and friends) exactly as before.

> Want the detailed manual process? Head over to
> [raspi_cluster_setup_manual.md](raspi_cluster_setup_manual.md).

## Configuration knobs

These environment variables tweak the automation. Set them inline (`SUGARKUBE_SERVERS=3 just up prod`)
or export them in your shell profile.

| Variable | Default | Purpose |
| --- | --- | --- |
| `SUGARKUBE_CLUSTER` | `sugar` | Logical cluster prefix advertised over mDNS |
| `SUGARKUBE_SERVERS` | `1` | Desired control-plane count per environment |
| `K3S_CHANNEL` | `stable` | Channel passed to the official k3s install script |
| `SUGARKUBE_TOKEN_DEV` / `INT` / `PROD` | _none_ | Preferred per-environment join tokens |
| `SUGARKUBE_TOKEN` | _none_ | Fallback token when an env-specific variant is absent |

Tokens gate node registration. Generate separate values per environment (e.g. from
`/var/lib/rancher/k3s/server/node-token` on the first server) and export them before running `just up`.

## Networking notes

- Avahi (`avahi-daemon` + `avahi-utils`) and `libnss-mdns` enable `.local` resolution via multicast
  DNS. The `prereqs` recipe installs them and ensures `/etc/nsswitch.conf` includes
  `mdns4_minimal [NOTFOUND=return] dns mdns4` so host lookups prefer mDNS on the LAN.
- Servers advertise the Kubernetes API as `_https._tcp` on port `6443` with Bonjour TXT records that
  tag the Sugarkube cluster (`cluster=<name>`), environment (`env=<env>`), and role (`role=server`).
  Agents use the `.local` hostname exposed over mDNS to join. After the first registration they
  rely on the embedded client-side load balancer built into k3s to discover/fail over to other
  servers, so IP address changes via DHCP are tolerated.
- Keep UDP 5353 (multicast) open across the subnet. `.local` is reserved for link-local mDNS by
  [RFC 6762](https://www.rfc-editor.org/rfc/rfc6762).

## Topologies

- **Default single server (`SUGARKUBE_SERVERS=1`)** – The first node per environment bootstraps k3s
  with the default SQLite datastore (no `--cluster-init`). Agents join against its `.local` name,
  inherit taints/labels, and the server keeps workloads off itself by default.
- **High-availability control plane (`SUGARKUBE_SERVERS>=3`)** – The first `just up <env>` run uses
  `--cluster-init` to start embedded etcd. Subsequent server nodes detect the desired count over mDNS
  and join via `--server https://<peer>:6443`. Use NVMe/SSD storage on Pis when running etcd; SD cards
  are not durable enough for the write profile.

Optional enhancements like a dedicated registration VIP or external load balancer remain compatible—
point `SUGARKUBE_TOKEN_*` clients at the chosen endpoint and keep the `.local` advertisements for LAN
peers.
