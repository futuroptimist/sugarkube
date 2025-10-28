---
personas:
  - hardware
  - software
---

# Raspberry Pi Cluster Setup (Quick Start)

`sugarkube` makes forming a Raspberry Pi cluster almost effortless: once your Pis boot the standard image and share the same LAN, you can create a per-environment k3s cluster with a single command per node.

---

## Happy Path: 3-server `dev` cluster in two runs

Every Raspberry Pi follows the same rhythm:

> **Time sync prerequisite**
> Sugarkube runs `scripts/check_time_sync.sh` before allowing a node to join. Make sure
> either chrony reports an offset under 500 ms or systemd-timesyncd is active and recently
> synchronized. Set `SUGARKUBE_FIX_TIME=1` to permit `chronyc -a makestep`, and
> `SUGARKUBE_STRICT_TIME=1` to make `just up` abort instead of warning when clocks drift.

```bash
export SUGARKUBE_SERVERS=3
just up dev              # 1st run patches memory cgroups and reboots

# after the Pi comes back and you SSH in again
export SUGARKUBE_SERVERS=3
just up dev              # 2nd run bootstraps or joins k3s
```

- **Why twice?** The first invocation runs `scripts/check_memory_cgroup.sh`, which edits the bootline if needed and triggers an automatic reboot. No manual editing of `/boot/cmdline.txt` is required—even on Raspberry Pi 5 hardware.
- **HA by default.** Exporting `SUGARKUBE_SERVERS=3` before each run tells `just up` to form an embedded-etcd quorum. Keep it at an odd number (3, 5, …) for resilient control planes.

### First control-plane node (e.g., `sugarkube0`)

After the second `just up dev` finishes, capture the join token that future nodes will need:

```bash
sudo cat /var/lib/rancher/k3s/server/node-token
```

Copy the long `K10…` string to a safe place—you will export it on every joining node.

> **Note**
> The first HA server does **not** need a token pre-exported. Sugarkube now allows
> the initial control-plane bootstrap to run without one so it can mint the token
> above for the rest of the cluster.

> **TLS SAN for mDNS**
> The bootstrap step also writes `/etc/rancher/k3s/config.yaml.d/10-sugarkube-tls.yaml`
> so the API certificate covers `sugarkube0.local`. Set `SUGARKUBE_API_REGADDR`
> before running `just up` if you advertise a VIP or load balancer—the address is
> added as an extra SAN to avoid TLS warnings when joining via that endpoint.

### Registration address (optional)

Multi-node clusters often sit behind a stable virtual IP or external load balancer.
Export `SUGARKUBE_API_REGADDR` before running `just up` so every join command uses
that address instead of whichever `.local` host happens to be the leader at the
moment.

```bash
# kube-vip advertising 10.99.0.5 on the control-plane VLAN
export SUGARKUBE_API_REGADDR="10.99.0.5"

# or an external load balancer DNS name
export SUGARKUBE_API_REGADDR="api.sugar.example"
```

Nodes still discover each other via mDNS, but the registration address is used for
`--server` URLs and `K3S_URL` so both servers and agents join through the VIP/LB.

### Remaining control-plane peers or agents

Each additional Pi repeats the same two `just up dev` runs. After the reboot, export the saved token before the second run so it can join the cluster:

```bash
export SUGARKUBE_SERVERS=3
export SUGARKUBE_TOKEN_DEV="K10abc123..."  # token from the first server
just up dev
```

When fewer than three servers are present, the node elects itself into the HA control plane; otherwise it settles in as an agent.

### Switch environments as needed

`just up <env>` works for `int`, `prod`, or other environments—you simply provide the matching token (for example `SUGARKUBE_TOKEN_INT`). Multiple environments can coexist on the same LAN as long as they advertise distinct tokens.

Need deeper operational playbooks? Continue with [docs/runbook.md](./runbook.md). When the control plane is steady, bootstrap GitOps with [`scripts/flux-bootstrap.sh`](../scripts/flux-bootstrap.sh) or `just flux-bootstrap env=dev`.

---

## Recover from a failed bootstrap/join

If a node accidentally **self-bootstrapped** (started its own embedded etcd) or joined the wrong
cluster, reset it and try again:

Safe, idempotent cleanup:

```bash
just wipe
```

What `just wipe` does:

- Runs the official uninstallers (`/usr/local/bin/k3s-uninstall.sh` and, if present,
  `k3s-agent-uninstall.sh`) to stop K3s and remove the local datastore and node config.
- Removes the mDNS/DNS-SD service file for the current cluster/env from `/etc/avahi/services/` and
  restarts Avahi so stale advertisements disappear.
- Executes a double-negative absence check that waits for the `_https._tcp:6443`
  advertisement to disappear **twice** before returning. This protects against
  cache reuse described in [RFC 6762](https://datatracker.ietf.org/doc/html/rfc6762)
  and makes the next bootstrap more deterministic.

After wiping, re-export the desired environment variables (and token if used) before retrying:

```bash
export SUGARKUBE_SERVERS=3
export SUGARKUBE_ENV=dev
# Optional: set SUGARKUBE_TOKEN_DEV to the leader's
# /var/lib/rancher/k3s/server/node-token
just up dev
```

### Verify discovery (mDNS)

To confirm the control plane is being advertised and discoverable before re-running `just up` on
other nodes:

```bash
avahi-browse --all --resolve --terminate | grep -A2 '_https._tcp'
# Look for port 6443 and TXT like: k3s=1, cluster=<name>, env=<env>, role=server
```

> **Note**
> mDNS/DNS-SD service files live in `/etc/avahi/services/`. Removing the relevant
> `k3s-*.service` file and reloading Avahi clears stale adverts.

If discovery looks healthy but the join hangs, enable the wire diagnostics and
readiness gates:

```bash
export SUGARKUBE_DEBUG_MDNS=1
export SUGARKUBE_MDNS_WIRE_PROOF=1
just up dev
```

`SUGARKUBE_MDNS_WIRE_PROOF` makes the helper refuse success until a TCP socket
to port 6443 opens, ensuring the join path is viable—not just advertised.

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

## Detailed Walkthrough (same subnet, DHCP friendly)

1. **Ensure network reachability**

   - All Pis must be on the same L2 subnet with multicast (UDP 5353) allowed.
   - Each Pi should be able to reach the internet.

2. **Run `just up dev` twice on the first control-plane node**

   The first run modifies memory cgroup settings if needed and reboots automatically. The second run installs `avahi-daemon`, `avahi-utils`, `libnss-mdns`, `libglib2.0-bin`, `tcpdump`, `curl`, and `jq`—with `libglib2.0-bin` enabling the `gdbus` D-Bus code path used for mDNS absence detection—bootstraps k3s as an HA server, publishes the API as `_https._tcp:6443` via Bonjour/mDNS with `cluster=sugar` and `env=dev` TXT records, and taints itself (`node-role.kubernetes.io/control-plane=true:NoSchedule`) so workloads prefer agents.

   > **HA choice**
   >
   > - `SUGARKUBE_SERVERS=1` keeps the first server on SQLite. Later nodes join as agents unless you promote them manually.
   > - `SUGARKUBE_SERVERS>=3` (recommended for HA) makes the first server initialise embedded etcd with `--cluster-init` and advertise itself via mDNS for other **servers** to join.

3. **Join worker or additional server nodes**

   Give the remaining Pis distinct hostnames such as `sugarkube1` and `sugarkube2` so their `.local` records resolve over the same L2 subnet. Each node runs `just up dev` twice, exporting both `SUGARKUBE_SERVERS` and the appropriate token before the second invocation.

4. **Switch environments easily**

   Each environment (`dev`, `int`, `prod`) maintains its own token and mDNS advertisement:

  ```bash
   just up int
   just up prod
   ```

   You can even run multiple environments on the same LAN simultaneously as long as they use different tokens.

   Discovery timing is captured in `ms_elapsed` log fields. Expect values under
   200 ms on a quiet LAN; higher numbers typically point to multicast flooding
   or pod-network churn. Sugarkube keeps the default Flannel VXLAN overlay that
   ships with K3s, so no extra CNI tuning is required during bootstrap.

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

- Need a clean slate? Use: [`just wipe`](#recover-from-a-failed-bootstrapjoin) for the full
  recovery flow.
  ```bash
  just wipe
  ```

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

- **mDNS**: Avahi (`avahi-daemon` + `avahi-utils`), `libnss-mdns`, and now
  `libglib2.0-bin` (for `gdbus`) enable deterministic `.local` hostname
  resolution. The `prereqs` recipe also installs `tcpdump` so `net_diag.sh`
  can capture UDP/5353 traffic when self-checks fail. It ensures
  `/etc/nsswitch.conf` includes `mdns4_minimal [NOTFOUND=return] dns mdns4`.

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
  List the currently discoverable control-plane hosts with:

  ```bash
  scripts/k3s-discover.sh --print-server-hosts
  ```

  Use the output to verify mDNS visibility before orchestrating multi-node joins or rehearsing with `pi rehearse`.

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

- **Verify mDNS discoverability**

  ```bash
  avahi-browse --all --resolve --terminate | grep -A2 '_https._tcp'
  ```

  Expect the API advert (`port 6443`) with TXT records `k3s=1`,
  `cluster=<name>`, `env=<env>`, `role=server`.

- **Reset everything**

  ```bash
  just wipe
  sudo reboot
  ```

  `just wipe` now wraps `scripts/wipe_node.sh`, making the cleanup idempotent and safe
  to rerun.

---

Once all three default nodes for an environment report `Ready`, proceed to the deployment playbooks (`token.place`, `dspace`, etc.) as usual.

> For a step-by-step deep dive, see
> [raspi_cluster_setup_manual.md](raspi_cluster_setup_manual.md).

---
