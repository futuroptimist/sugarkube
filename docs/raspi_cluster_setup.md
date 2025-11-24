---
personas:
  - hardware
  - software
---

# Raspberry Pi Cluster Setup (Quick Start)

**📚 Part 2 of 3** in the [Raspberry Pi cluster series](index.md#raspberry-pi-cluster-series)
- **Previous:** [Part 1 - Manual Setup](raspi_cluster_setup_manual.md)
- **Next:** [Part 3 - Operations & Helm](raspi_cluster_operations.md)

`sugarkube` makes forming a Raspberry Pi cluster almost effortless: once your Pis boot the standard image and share the same LAN, you can create a per-environment k3s cluster with a single command per node.

> **Next step:** When the control plane is stable, continue with
> [raspi_cluster_operations.md](./raspi_cluster_operations.md) for log capture,
> Helm, and other day-two workflows.

## Clone SD to SSD (happy path)

If your Raspberry Pi is booted from the SD card and you have an NVMe/SSD attached, you can
migrate the system to the SSD using the `clone-ssd` helper. This is the short “happy path” for
the common case.

1. Boot the Pi from the freshly flashed SD card with the NVMe/SSD connected.

2. SSH into the Pi as `pi` and change into the `sugarkube` repo:

   ```bash
   cd ~/sugarkube
   ```

3. Use `lsblk` to identify the NVMe/SSD device:

   ```bash
   lsblk
   ```

   Look for a device with:

   - `TYPE` of `disk`, and
   - a `NAME` like `nvme0n1` (for an NVMe drive) or another block device representing your SSD.

   The boot SD card will typically appear as something like `mmcblk0` with the root/boot
   partitions under it. The NVMe/SSD will usually have a different name, e.g. `nvme0n1`.

4. Run the clone helper, specifying the target device (for example, if your NVMe shows up as
   `/dev/nvme0n1`):

   ```bash
   sudo TARGET=/dev/nvme0n1 WIPE=1 just clone-ssd
   ```

   The `clone-ssd` recipe will run preflight checks, clone the SD card to the SSD/NVMe, and
   update boot configuration so the system can boot from the SSD. It will print a success message
   once the clone is complete.

5. After the clone completes, cleanly shut down the Pi:

   ```bash
   sudo shutdown -h now
   ```

   Wait for the Pi to power off completely, then remove the SD card. On the next power-on, the Pi
   should boot from the SSD/NVMe.

After cloning to SSD and rebooting, see
[Configure Git identity and GitHub access](#configure-git-identity-and-github-access-pi) to set up
commits and pushes from the node.

For a more detailed walkthrough of the SD→NVMe process (including validation and recovery steps),
see:

- [Pi image quickstart](./pi_image_quickstart.md)
- [SD to NVMe migration](./storage/sd-to-nvme.md)

## Configure Git identity and GitHub access (Pi)

After re-imaging a Pi and cloning the `sugarkube` repo, configure Git and GitHub so you can commit
and push logs and changes from the node.

### 1. Set Git author identity

Set the display name and GitHub noreply email for commits made from the `pi` user (replace the
placeholders with your details):

```bash
git config --global user.name "Your Name"
git config --global user.email "your_github_username@users.noreply.github.com"
```

- `user.name` is the display name that will appear on commits from this Pi.
- `user.email` uses your GitHub noreply address so commits map to your GitHub account.

### 2. Authenticate Git pushes via GitHub CLI

Install GitHub CLI if needed and start the device/browser login flow:

```bash
# Install GitHub CLI if needed
type gh >/dev/null 2>&1 || sudo apt-get update && sudo apt-get install -y gh

# Start the login flow
gh auth login
```

Choose the following when prompted:

- **GitHub.com**
- **HTTPS** for the Git protocol
- **Yes** to "Authenticate Git with your GitHub credentials?"
- **Login with a web browser**

The CLI will show a one-time code and a URL like `https://github.com/login/device`. On a computer
where you are already signed into GitHub, open that URL, enter the code, approve the login, and
return to the Pi. Once it reports "Authentication complete," verify pushes work:

```bash
git remote -v
git push origin main
```

You should now be able to push without retyping your username and password each time.

## Helper commands cheat sheet

Quick reference for the most common recipes when bringing up a 3-node HA dev cluster:

- **`just ha3 env=dev`** — main path to bring up or re-run the 3-node dev cluster
  _When to use:_ Run this twice per server during initial bring-up (first run patches memory cgroups and reboots, second run bootstraps or joins k3s). Also use when adding new nodes to an existing cluster.

- **`just save-logs env=dev`** — run cluster bring-up with `SAVE_DEBUG_LOGS=1` into `logs/up/`
  _When to use:_ Capture sanitized logs during the second run for troubleshooting or documentation. The logs are automatically filtered to remove sensitive data.

- **`just cat-node-token`** — display the k3s node token for joining nodes
  _When to use:_ After bootstrapping the first node, use this to retrieve the token that other nodes need to join the cluster. Copy the output and set it as `SUGARKUBE_TOKEN_DEV` on subsequent nodes.

> **💡 Troubleshooting tip:** If you encounter issues during setup, captured logs can help diagnose problems. See the [Raspberry Pi Cluster Troubleshooting Guide](raspi_cluster_troubleshooting.md) for help interpreting log output and resolving common issues.

## How Discovery Works

Nodes discover each other **automatically** via mDNS (multicast DNS) service browsing:

1. **First node bootstraps**: When you run `just up dev` on the first Pi, it starts k3s and publishes an mDNS service advertisement on the local network saying "k3s API available here at port 6443"

2. **Subsequent nodes discover**: When you run `just up dev` on additional Pis, they use `avahi-browse` to scan the local network for any node advertising the k3s service

3. **Automatic joining**: Once a node finds an advertised k3s server, it validates the API is responding, then joins using the token you provided

**Key point:** There is no pre-configuration, hostname registry, or "previously discovered" node list. Discovery happens dynamically at runtime through mDNS service advertisements. Nodes can have any hostname - they're discovered by their advertised services, not by assumed naming patterns.

### Technical Details: mDNS Service Browsing

**Service Advertisement:**
- Bootstrap nodes publish an Avahi service file to `/etc/avahi/services/`
- Service type: `_k3s-<cluster>-<environment>._tcp` (e.g., `_k3s-sugar-dev._tcp`)
- Includes TXT records: cluster name, environment, role (server/agent), and phase info
- Avahi daemon multicasts this on UDP port 5353 to `224.0.0.251` (IPv4) or `ff02::fb` (IPv6)

**Service Discovery:**
- Joining nodes run `avahi-browse --parsable --resolve _k3s-sugar-dev._tcp`
- By default, avahi-browse waits for actual multicast responses (not just cached entries)
- This is essential: on first boot, the cache is empty, so waiting for network responses is required
- Discovery timeout: 10 seconds by default (configurable via `SUGARKUBE_MDNS_QUERY_TIMEOUT`)

**Why this works without configuration:**
- mDNS is link-local: automatically works on any L2 network segment
- No DNS server needed: nodes directly respond to multicast queries
- No hostname assumptions: services are found by type, not by assumed naming patterns
- Zero-config: as long as nodes share the same LAN and multicast is allowed, discovery happens

**Troubleshooting tip:** If discovery fails, it's usually one of these issues:
1. Multicast blocked by network/firewall (UDP 5353)
2. Nodes on different L2 subnets (multicast doesn't route)
3. Avahi daemon not running on one or both nodes

---

## Happy Path: 3-server `dev` cluster in two runs

### Bootstrap vs Join: Token Behavior

**Explicit user intent controls whether a node bootstraps or joins:**

- **No token set** (`SUGARKUBE_TOKEN_DEV` not exported): Node **bootstraps** a new cluster
  ```bash
  just up dev  # Bootstraps new cluster, mints token for others to use
  ```

- **Token set** (`SUGARKUBE_TOKEN_DEV` exported): Node **joins** existing cluster
  ```bash
  export SUGARKUBE_TOKEN_DEV="K10abc123..."  # Token from first node
  just up dev  # Joins existing cluster using provided token
  ```

> **Key principle:** The presence or absence of `SUGARKUBE_TOKEN_DEV` (or `SUGARKUBE_TOKEN_INT`, `SUGARKUBE_TOKEN_PROD`) is how you signal your intent. Without a token, `just up dev` creates a new cluster. With a token, it joins an existing one.

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

> Prefer a one-liner? `just ha3 env=dev` wraps `SUGARKUBE_SERVERS=3 just up dev`
> so you can rerun the HA flow without re-exporting variables.

- **Why twice?** The first invocation runs `scripts/check_memory_cgroup.sh`, which edits the bootline if needed and triggers an automatic reboot. No manual editing of `/boot/cmdline.txt` is required—even on Raspberry Pi 5 hardware.
- **HA by default.** Exporting `SUGARKUBE_SERVERS=3` before each run tells `just up` to form an embedded-etcd quorum. Keep it at an odd number (3, 5, …) for resilient control planes.

### First control-plane node (e.g., `sugarkube0`)

After the second `just up dev` finishes, capture the join token that future nodes will need:

```bash
sudo cat /var/lib/rancher/k3s/server/node-token
```

`just cat-node-token` wraps the same command via `sudo` so you can copy the token
without retyping the file path.

Copy the long `K10…` string to a safe place—you will export it on every joining node.

> **Important: Bootstrap vs Join**
> The first node does **not** need `SUGARKUBE_TOKEN_DEV` set. Running `just up dev`
> without the token environment variable tells Sugarkube to **bootstrap** a new cluster
> and mint the token above. Subsequent nodes **must** export `SUGARKUBE_TOKEN_DEV`
> before running `just up dev` to signal they should **join** the existing cluster, not
> create a new one.

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

Each additional Pi repeats the same two `just up dev` runs. After the reboot, export the
saved token before the second run so it can join the cluster:

```bash
export SUGARKUBE_SERVERS=3
export SUGARKUBE_TOKEN_DEV="K10abc123..."  # token from the first server
just up dev
```

When fewer than three servers are present, the node elects itself into the HA control plane;
otherwise it settles in as an agent.

> Need sanitized log capture or mDNS hostname filtering? See
> [raspi_cluster_operations.md](./raspi_cluster_operations.md#step-2-capture-and-commit-sanitized-bring-up-logs)
> for the dedicated flow and the new `just save-logs env=<env>` wrapper.

Short on time? You can still capture sanitized bootstrap logs directly from this
guide. Set `SAVE_DEBUG_LOGS=1` for the **second** `just up` run, then unset it so
future commands stay quiet:

```bash
SAVE_DEBUG_LOGS=1 just up dev
unset SAVE_DEBUG_LOGS  # stop logging in this shell
```

This streams console output through `scripts/filter_debug_log.py` and writes a
timestamped copy under `logs/up/` so you can attach the file to bug reports.

### Switch environments as needed

`just up <env>` works for `int`, `prod`, or other environments—you simply provide the
matching token (for example `SUGARKUBE_TOKEN_INT`). Multiple environments can coexist on the
same LAN as long as they advertise distinct tokens.

Need deeper operational playbooks? Continue with [docs/runbook.md](./runbook.md). When the
control plane is steady, bootstrap GitOps with [`scripts/flux-bootstrap.sh`](../scripts/flux-bootstrap.sh)
or `just flux-bootstrap env=dev`.

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
- Clears every environment variable documented in this guide (for example
  `SUGARKUBE_SERVERS`, the per-environment tokens, `SAVE_DEBUG_LOGS`, `K3S_CHANNEL`,
  and the mDNS diagnostics toggles) and writes a helper snippet to
  `${XDG_CACHE_HOME:-~/.cache}/sugarkube/wipe-env.sh` that you can `source` in your
  interactive shell to reset exports there as well.

After wiping, re-export the desired environment variables (and token if used) before retrying:

```bash
cleanup_snippet="${XDG_CACHE_HOME:-$HOME/.cache}/sugarkube/wipe-env.sh"
[ -f "${cleanup_snippet}" ] && source "${cleanup_snippet}"  # clears your shell exports
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

> **💡 Troubleshooting:** For detailed guidance on diagnosing bootstrap and join failures, including how to interpret discovery logs and resolve mDNS issues, see the [Raspberry Pi Cluster Troubleshooting Guide](raspi_cluster_troubleshooting.md).

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

Operational commands—`just status`, `just kubeconfig env=<env>`, log capture, and
the `just wipe` recovery loop—now live in
[raspi_cluster_operations.md](./raspi_cluster_operations.md). Follow that guide
for Helm installs, Flux bootstraps, and workstation access. For deeper SRE
playbooks continue with [docs/runbook.md](./runbook.md).

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
| `SUGARKUBE_SKIP_ABSENCE_GATE` | `1` | Skip Avahi restart at discovery time (Phase 2: enabled by default) |
| `SUGARKUBE_SIMPLE_DISCOVERY` | `1` | Use mDNS service browsing for discovery (Phase 3: enabled by default) |
| `SUGARKUBE_SKIP_SERVICE_ADVERTISEMENT` | `0` | When set to `1`, skip mDNS service publishing (Phase 4: disabled by default - nodes advertise) |
| `SUGARKUBE_MDNS_NO_TERMINATE` | `1` | Skip `--terminate` flag in avahi-browse to wait for network responses (recommended for initial cluster formation) |
| `SUGARKUBE_MDNS_QUERY_TIMEOUT` | `10.0` | Timeout in seconds for mDNS queries (increase if discovery is slow) |

### Generating Tokens Manually
If you ever need to regenerate a token, run this on a control-plane node:
```bash
sudo cat /var/lib/rancher/k3s/server/node-token
```
or, if that file is missing, reinstall the server (`just up dev` on a fresh node) and grab the new token.

### mDNS Discovery Simplification (Phases 2-4) - Enabled by Default

The discovery system has been significantly simplified to improve reliability and performance. All simplifications are **enabled by default** in new deployments.

#### Phase 2: Skip Absence Gate (Default: Enabled)

The system now trusts systemd to keep Avahi running instead of restarting it before discovery. This eliminates restart-related race conditions and saves 5-25 seconds per node.

To revert to the legacy behavior (restart Avahi before discovery):
```bash
export SUGARKUBE_SKIP_ABSENCE_GATE=0
just up dev
```

#### Phase 3: Simplified Discovery (Default: Enabled)

Discovery uses mDNS service browsing to find any k3s nodes advertising themselves on the network:

**How it works:**
1. When a node starts k3s, it publishes an mDNS service record (via Avahi) advertising the k3s API on port 6443
2. Joining nodes use `avahi-browse` to scan the local network for advertised k3s services
3. The first responsive server found is used for joining
4. **No hostname assumptions:** Any node with any hostname can be discovered, as long as it advertises the k3s service

**Key benefits:**
- Zero-configuration: No need to know hostnames in advance
- Flexible naming: Use any hostname pattern (`pi-node-1.local`, `cluster-server.local`, etc.)
- Dynamic discovery: Nodes find each other automatically via service advertisements
- Simplified flow: Eliminates leader election complexity while maintaining proper service discovery

**What was simplified:**
The discovery process now skips the leader election phase but **still uses proper mDNS service browsing**. This reduces discovery time to 10-20 seconds while maintaining zero-configuration networking.

To revert to the legacy behavior (service-based discovery with leader election):
```bash
export SUGARKUBE_SIMPLE_DISCOVERY=0
just up dev
```

#### Phase 4: Service Advertisement (Default: Enabled)

**By default, nodes advertise their k3s API via mDNS service records.** This allows Phase 3 simplified discovery to find servers using `avahi-browse`.

When service advertisement is enabled (default), bootstrap nodes publish service records to `/etc/avahi/services/` that include:
- Service type: `_k3s-{cluster}-{environment}._tcp` (e.g., `_k3s-sugar-dev._tcp`)
- Port: 6443 (k3s API)
- TXT records: cluster name, environment, role, and phase information

This enables joining nodes to discover available k3s servers without needing to know hostnames in advance.

To disable service advertisement and rely only on `.local` hostname resolution:
```bash
export SUGARKUBE_SKIP_SERVICE_ADVERTISEMENT=1
just up dev
```

**Note**: Disabling service advertisement (Phase 4) is incompatible with simplified discovery (Phase 3). If you disable advertisement, you must also disable simplified discovery by setting `SUGARKUBE_SIMPLE_DISCOVERY=0`.

For more details on the phased simplification roadmap, see `notes/2025-11-14-mdns-discovery-fixes-and-simplification-roadmap.md`.

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

> **📖 Complete Troubleshooting Guide:** For comprehensive troubleshooting guidance including log interpretation, common failure scenarios, and step-by-step diagnostics, see the dedicated [Raspberry Pi Cluster Troubleshooting Guide](raspi_cluster_troubleshooting.md).

The following quick tips address the most common issues:

- **Error: `SUGARKUBE_TOKEN (or per-env variant) required`**

  `just up` now reads the generated token from `/var/lib/rancher/k3s/server/node-token`
  (or `/boot/sugarkube-node-token`) when bootstrapping a single-server cluster, so you
  should only see this error when orchestrating multi-server or agent joins. Export the
  appropriate environment variable with the control-plane token before retrying.

- **Cluster discovery fails: "No joinable servers found via mDNS service browsing"**

  This means the joining node couldn't find any k3s servers advertising on the network.

  **Check the basics:**
  - Confirm multicast (UDP 5353) is allowed on your network/firewall
  - Verify both nodes are on the same L2 subnet
  - Verify `avahi-daemon` is running on both nodes: `sudo systemctl status avahi-daemon`
  - Check that `/etc/nsswitch.conf` contains `mdns4_minimal`

  **Verify the bootstrap node is advertising:**
  Run this on the bootstrap node (sugarkube0):
  ```bash
  # Should show the k3s service with port 6443
  avahi-browse --all --resolve --terminate | grep -A5 'k3s-sugar-dev'
  ```

  **Verify the joining node can see the advertisement:**
  Run this on the joining node (sugarkube1):
  ```bash
  # Should show services from sugarkube0
  avahi-browse --all --resolve | grep -A5 'k3s-sugar-dev'
  # Press Ctrl+C after a few seconds
  ```

  **If avahi-browse sees nothing:**
  This usually indicates a network issue (multicast blocked) or Avahi daemon not running.

  **Enable detailed mDNS debugging:**
  ```bash
  export SUGARKUBE_DEBUG=1
  export SUGARKUBE_MDNS_WIRE_PROOF=1
  just up dev 2>&1 | tee debug.log
  ```

  Check `debug.log` for lines starting with `[k3s-discover mdns]` to see what avahi-browse
  is finding (or not finding).

- **Discovery takes too long or times out**

  By default, avahi-browse waits for actual mDNS multicast responses (not just cached entries).
  This is necessary for initial cluster formation but can be slow on congested networks.

  - Increase the timeout: `export SUGARKUBE_MDNS_QUERY_TIMEOUT=30`
  - Check network quality: high packet loss or multicast flooding can delay responses
  - Verify no mDNS reflector or proxy is interfering with multicast

- **Verify mDNS discoverability**

  ```bash
  avahi-browse --all --resolve --terminate | grep -A2 '_https._tcp'
  ```

  Expect the API advert (`port 6443`) with TXT records `k3s=1`,
  `cluster=<name>`, `env=<env>`, `role=server`.

  **Note:** Using `--terminate` flag is fast but only shows cached entries. If you just
  published a service, you might need to wait a few seconds or omit `--terminate` to see
  fresh results.

- **Reset everything**

  ```bash
  just wipe
  sudo reboot
  ```

  `just wipe` now wraps `scripts/wipe_node.sh`, making the cleanup idempotent and safe
  to rerun.

- **k3s service starts but API never becomes ready (times out after 120s)**

  If discovery succeeds and k3s installs but the API never becomes ready, check the k3s service logs:

  **On the node with the problem (e.g., sugarkube1):**
  ```bash
  # Check k3s service status
  sudo systemctl status k3s

  # View recent k3s logs
  sudo journalctl -u k3s -n 100 --no-pager

  # Check for certificate errors
  sudo journalctl -u k3s | grep -i "certificate\|tls\|x509" | tail -20

  # Check for connection errors
  sudo journalctl -u k3s | grep -i "connection\|refused\|timeout" | tail -20

  # Verify k3s can reach the remote server
  curl -k https://sugarkube0.local:6443/livez
  # Should return HTTP 401 or 200 (both mean API is alive)

  # Check if k3s is trying to connect to the right server
  grep K3S_URL /etc/systemd/system/k3s.service.env
  grep ExecStart /etc/systemd/system/k3s.service | grep -o 'server [^ ]*'

  # Verify k3s token is set correctly
  grep K3S_TOKEN /etc/systemd/system/k3s.service.env | wc -c
  # Should show >50 characters if token is present
  ```

  **On the bootstrap node (e.g., sugarkube0):**
  ```bash
  # Check if k3s server is running and responsive
  sudo kubectl get nodes

  # Verify the API certificate includes IP addresses
  openssl s_client -connect localhost:6443 </dev/null 2>/dev/null | \
    openssl x509 -text | grep -A1 "Subject Alternative Name"
  # Should include both hostnames AND IP addresses

  # Check k3s logs for connection attempts from joining nodes
  sudo journalctl -u k3s | grep -E "join|etcd|member" | tail -30

  # Verify etcd cluster health (for HA clusters)
  sudo k3s etcd-snapshot save --name diagnostic
  sudo k3s etcd-snapshot ls
  ```

  **Network connectivity between nodes:**
  ```bash
  # From joining node (sugarkube1), test connectivity to bootstrap node
  nc -zv sugarkube0.local 6443  # k3s API
  nc -zv sugarkube0.local 2379  # etcd client
  nc -zv sugarkube0.local 2380  # etcd peer

  # Check if ports are actually listening on sugarkube0
  # Run on sugarkube0:
  sudo ss -tlnp | grep -E ":(6443|2379|2380)"

  # Verify no firewall is blocking
  # Run on both nodes:
  sudo iptables -L -n | grep -E "6443|2379|2380"
  sudo ip6tables -L -n | grep -E "6443|2379|2380"
  ```

  **Common causes:**
  - **Missing IP in TLS certificate**: Bootstrap node's certificate doesn't include its IP address as a SAN
  - **Wrong server URL**: k3s is trying to connect using hostname instead of IP address
  - **Token mismatch**: Token in SUGARKUBE_TOKEN_DEV doesn't match the actual node-token
  - **Firewall rules**: Ports 6443, 2379, 2380 blocked between nodes
  - **Time synchronization**: Clock drift >500ms prevents etcd cluster formation
  - **Network partition**: Nodes can ping each other but can't establish TCP connections

---

Once all three default nodes for an environment report `Ready`, proceed to the deployment
playbooks (`token.place`, `dspace`, etc.) as usual. The base bootstrap does **not** install an
ingress controller.

Install Traefik using the [Traefik ingress][traefik-ingress] steps before rolling out HTTP
applications.

[traefik-ingress]: ./raspi_cluster_operations.md#install-and-verify-traefik-ingress

> For a step-by-step deep dive, see
> [raspi_cluster_setup_manual.md](raspi_cluster_setup_manual.md).

## Exercises

Reinforce your k3s cluster knowledge with these practical tasks:

1. **Modified environment:** To upgrade k3s on an existing cluster, first stop the k3s service with `sudo systemctl stop k3s` (or set `INSTALL_K3S_SKIP_START=false`), then re-run `just ha3 env=dev` with `K3S_CHANNEL=latest` exported to use a newer k3s version. After the upgrade, check `kubectl version` to verify the control plane now reports the updated version.

2. **Node label inspection:** After bringing up your cluster, use `kubectl get nodes --show-labels` to observe the labels automatically applied by k3s (e.g., `node-role.kubernetes.io/control-plane`). Note which nodes have the `NoSchedule` taint preventing workload scheduling.

3. **Discovery validation:** Before joining a second node, run `avahi-browse --all --resolve --terminate | grep -A5 'k3s-sugar-dev'` on the joining node to confirm it can discover the control plane's mDNS advertisement. Record the hostname and port displayed.

4. **Recovery practice:** On a test node, deliberately join it to the wrong cluster by exporting an incorrect token, then use `just wipe` to reset it. After wiping, verify `/var/lib/rancher/k3s/` no longer exists and re-run `just ha3 env=dev` with the correct token.

5. **Log capture and review:** Run `just save-logs env=dev` during a node bring-up and locate the sanitized log file in `logs/up/`. Examine the file to find the mDNS discovery timing (look for `ms_elapsed` fields) and identify any network delays over 200ms.

---
