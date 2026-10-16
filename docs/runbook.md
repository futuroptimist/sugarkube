# Sugarkube Platform Runbook

This runbook documents the expected flow for bringing a three-node Raspberry Pi 5 k3s cluster
online, keeping it healthy, and restoring service after failures. All commands assume an
operator workstation with the `just`, `flux`, `kubectl`, `rg` (ripgrep), and `sops` CLIs installed.

## 1. Bootstrap the first server

1. Flash the sugarkube OS image to the NVMe module or SD card as described in
   `docs/network_setup.md`.
2. Copy `docs/k3s/config-examples/server-first.yaml` to `/etc/rancher/k3s/config.yaml` and
   replace the placeholder values:
   - `token`: shared bootstrap token for all servers.
   - `tls-san`: include the kube-vip IP and any management hostnames for the chosen environment.
   - `kube-vip`: confirm the VIP matches `clusters/<env>/patches/kube-vip-values.yaml` so that the
     join configuration aligns with the Flux-managed manifest.
   - `etcd-snapshot-*`: leave the defaults in place for the built-in schedule and retention.
   - `#etcd-s3-*`: uncomment and populate the S3-compatible endpoint, bucket, and credentials once
     remote snapshot archiving is available.
 - `disable`: Traefik remains the default ingress; keep the bundled ServiceLB enabled until a
   replacement such as MetalLB is installed.

> **Note:** Kubernetes 1.33 promoted kube-proxy's nftables backend to GA, so the
> Sugarkube image enables it by default via
> `/etc/rancher/k3s/config.yaml.d/10-kube-proxy.yaml`. Older
> clusters can override the drop-in (or set `K3S_KUBE_PROXY_MODE=iptables`
> before rerunning the installer) to stick with the legacy iptables proxy if
> necessary. When the drop-in is present `pi_node_verifier` records
> `kube_proxy_dataplane: pass`, which confirms the nftables backend is available.
3. Start k3s on the first control-plane:

   ```bash
   sudo systemctl enable --now k3s
   sudo k3s kubectl get nodes -o wide
   ```

4. Confirm the contacted API server and its etcd dependency are ready:

   ```bash
   kubectl get --raw='/readyz?verbose' | rg 'etcd|readyz check passed'
   ```

   This proves readiness only for the contacted API server and that server's etcd dependency. It
   is not a complete per-member etcd health, consistency, or latency report. Optional deeper
   inspection requires a separately installed compatible `etcdctl` using the official K3s-managed
   endpoints and client-certificate paths. Never print certificate, private-key, or Secret
   contents.

## 2. Deploy kube-vip and verify the virtual IP

1. Apply the `kube-vip` manifest once the first node is up so that the virtual IP is available
   before joining additional servers:

   ```bash
   sudo k3s kubectl apply -k platform/kube-vip
   ```

2. Ping the VIP from your workstation and verify ARP resolution points to the active control
   plane.

## 3. Join the remaining servers

1. Copy `docs/k3s/config-examples/server-join.yaml` to the remaining nodes and update the shared
   token and VIP fields so that they match the values defined in the environment patch at
   `clusters/<env>/patches/kube-vip-values.yaml`.
2. Start k3s on each server and confirm all three nodes reach `Ready`.
3. Optionally taint the control-plane nodes as shown in
   `docs/k3s/config-examples/server-taints.md` to keep general workloads off the control plane.

## Node recovery (mis-bootstrap)

1. Run the safe reset: `just wipe`.
2. Re-export `SUGARKUBE_ENV`, `SUGARKUBE_SERVERS`, and any per-environment token
   (`SUGARKUBE_TOKEN_*`).
3. Rerun `just up <env>` with the corrected settings.

Verify discovery (mDNS):

```bash
avahi-browse --all --resolve --terminate | grep -A2 '_https._tcp'
```

### mDNS readiness gates

Sugarkube runs two readiness gates before calling a node healthy:

1. **Absence gate (double-negative):** `just wipe` and the discovery scripts
   watch the `_https._tcp` advertisement disappear **twice** before returning.
   This protects the next bootstrap from cached responses permitted under
   [RFC 6762](https://datatracker.ietf.org/doc/html/rfc6762).
2. **Port 6443 wire proof:** When `SUGARKUBE_MDNS_WIRE_PROOF=1` (enabled by
   default whenever `tcpdump` is available) the helpers refuse to mark discovery
   successful until a
   TCP connection to port 6443 completes. This mirrors the `k3s` readiness check
   that agents use and aligns with the Flannel-backed service network that ships
   with K3s.

Discovery logs always include an `ms_elapsed` field. Values under 200 ms are
normal on a quiet LAN with the default Flannel VXLAN overlay. Sustained values
in the hundreds of milliseconds indicate congestion or multicast drops—enable
`SUGARKUBE_DEBUG_MDNS=1` to capture Avahi traces and
`SUGARKUBE_MDNS_DBUS=0` to fall back to the CLI path if D-Bus is blocked.

The Raspberry Pi setup runbook documents the sanitized mDNS debugging workflow
(`logs/debug-mdns.sh`) so operators can capture redacted traces during
bootstrap without leaking IPs or MACs. See the "Capture sanitized debug logs"
section of the quick start:
https://github.com/futuroptimist/sugarkube/blob/main/docs/raspi_cluster_setup.md.

### mDNS Troubleshooting (Avahi)

- **Atomic publish:** Write Avahi service definitions to a temporary file and
  rename them into `/etc/avahi/services/`. Avahi only reacts to atomic moves,
  so `install -m0644 foo.service /etc/avahi/services/` (or `cp` to a temp path
  followed by `mv`) avoids partially written XML.
- **File permissions:** Service manifests must be readable by the chrooted
  daemon. Keep them at mode `0644`; stricter permissions cause
  `failed_to_read_service_file` journal warnings.
- **Chrooted paths:** Avahi logs paths under `/services/…` because the daemon
  chroots into `/var/run/avahi-daemon/`. Treat those prefixes as relative to
  the chroot when mapping back to the host filesystem.
- **Static host publishes:** `/etc/avahi/hosts` uses the same
  `IP-address hostname` format as `/etc/hosts`, but the entries are published
  over mDNS by Avahi—they are not a Name Service Switch guarantee. Keep the
  list short and rely on dynamic service files for SRV/TXT records.

## 4. Bootstrap Flux and secrets

Flux bootstrapping defaults to the production overlay. Pass `env=<env>` to the Just recipes or set
`CLUSTER_ENV=<env>` when calling `scripts/flux-bootstrap.sh` to target a different cluster. The
bootstrap script applies `flux/gotk-sync.yaml` and `flux/gotk-components.yaml` as-is, then patches
the Flux `Kustomization` path to `./clusters/<env>`.

### High-level command

Run the high-level Just recipe to install Flux, apply Git sources, and reconcile the platform.

```bash
just flux-bootstrap env=dev
just platform-apply env=dev
```

Replace `dev` with `staging` or `prod` for the target environment (`int` remains a deprecated alias for staging). `flux-bootstrap` wraps
`scripts/flux-bootstrap.sh` (safe to run multiple times) and patches the Flux `Kustomization`
path to the selected environment after installing the controllers. `platform-apply` requests an
immediate Flux reconciliation of the platform stack.

To rotate age keys or rewrap secrets after editing them with `sops`, run:

```bash
just seal-secrets env=dev
```

Ensure `SOPS_AGE_KEY` or `SOPS_AGE_KEY_FILE` points to the private key so that Flux and the CLI can
decrypt manifests under `clusters/*/secrets/` and `platform/*/secrets/` as governed by `.sops.yaml`.

### Low-level equivalent

If you prefer to execute each step manually, follow the procedure in
`scripts/flux-bootstrap.sh`:

1. Create the `flux-system` namespace.
2. Export and apply the Flux controllers using `flux install --export`.
3. Apply `flux/gotk-sync.yaml` (which defaults to `./clusters/prod`) and
   `flux/gotk-components.yaml` with server-side apply, then patch the
   `Kustomization` path for the target environment:

   ```bash
   kubectl apply -f flux/gotk-sync.yaml --server-side --force-conflicts
   kubectl apply -f flux/gotk-components.yaml --server-side --force-conflicts
   kubectl -n flux-system patch kustomization platform --type=merge \
     -p '{"spec":{"path":"./clusters/dev"}}'
   ```
4. Create (or rotate) the `sops-age` secret containing the private age key.
5. Reconcile the `flux-system` Git source and the `platform` Kustomization.

## 5. Platform reconciliation checklist

After Flux begins reconciling, verify the critical components:

- `kube-vip` DaemonSet pods are running on all control-plane nodes.
- `cert-manager` and the `letsencrypt-*` issuers show `Ready` status.
- `cloudflared` Deployments report a connected tunnel for each hostname and expose metrics via the
  autogenerated ServiceMonitor.
- `longhorn` UI is reachable via the kube-vip VIP and the default StorageClass is `longhorn`.
- `kube-prometheus-stack`, `loki`, and `promtail` pods are healthy in the `monitoring` namespace and
  scrape Traefik through the dedicated `ServiceMonitor`.

### Cloudflare Tunnel on Kubernetes

`platform/cloudflared/configmap.yaml` owns the shared Helm values for the Cloudflare Tunnel chart.
Per-environment overrides live under `clusters/<env>/patches/cloudflared-values.yaml` so each
cluster can publish its own hostname set while keeping the base tuned for arm64. The tunnel fronts
Traefik, meaning ingress traffic exits the cluster outbound only—no inbound ports are opened on the
Pi hosts. Flux health checks now gate reconciliation on the `cloudflared` Deployment so tunnels must
be healthy before promotions continue.

### Cloudflare DNS token scope

Provision a Cloudflare **API Token** that is restricted to the specific zone used by the cluster.
Grant `Zone:Read` and `DNS:Edit` only. Store the token in the new `external-dns-cloudflare`
secrets under `clusters/*/secrets/` (SOPS encrypted), which are referenced when the optional
`external-dns` overlay is enabled. Rotate the token by updating the encrypted secret and running
`just seal-secrets env=<env>` to rewrap it for Flux.

### Optional external-dns overlay

The repository keeps ExternalDNS disabled by default. To enable it, add
`../../platform/overlays/external-dns` to the `resources` block in
`clusters/<env>/kustomization.yaml`. The base platform now provisions the `external-dns` namespace so
the SOPS secret can reconcile even when the overlay is disabled. The overlay attaches the
`ghcr-pull-secret` image pull credentials, unsuspends the HelmRelease, and passes the Cloudflare
token via the `CF_API_TOKEN` environment variable. Review Cloudflare for TXT ownership records
(`external-dns` claims each hostname) and ensure the ingress resources you expect to publish carry
stable hostnames to avoid churn.

### Validation commands

Use these quick checks after bootstrap or recovery to confirm the control plane is healthy before moving on to workload verification:

```bash
just status
kubectl -n kube-system get daemonset kube-vip
kubectl -n kube-system get svc traefik
```

### cert-manager DNS-01 troubleshooting (non-Flux clusters)

When Flux is not installed, `kubectl apply -k platform/cert-manager` will fail at `HelmRelease` resources. Use `just cert-manager-install` and `just cert-manager-issuers-apply email=<email>` instead.

Common failure modes:

- **Missing cert-manager CRDs** (`no matches for kind "Certificate"` / `"ClusterIssuer"`): reinstall cert-manager with CRDs enabled.
- **`clusterissuer.cert-manager.io` resource type missing**: controllers/CRDs are not fully installed yet.
- **Literal `$(CERT_MANAGER_EMAIL)` in ClusterIssuer**: issuer was applied from Flux-era template without replacement; reapply with `just cert-manager-issuers-apply email=<email>`.
- **Missing `cloudflare-api-token` secret**: for staging, follow the staging-only, stdin-safe
  workflow in `docs/staging-cert-manager.md`. The tooling in that guide deliberately refuses to
  run against non-staging clusters. For other environments, use an environment-specific,
  reviewed procedure that passes the token over standard input to `kubectl create secret generic
  --from-file=api-token=/dev/stdin`; never put the token in a command argument or visible shell
  environment assignment.
  In staging, run the guarded `cert-manager-certificate-verify-authorization` recipe before one
  recovery attempt; it requires the exact `sugar-staging` context. Structural checks do not prove
  Cloudflare dashboard scope until a DNS-01 Challenge succeeds.
- **Challenge cleanup errors after successful issuance**: Cloudflare API token is missing `Zone:Read` and/or is scoped to the wrong zone.

Validation sequence:

```bash
kubectl get crd | grep cert-manager.io
kubectl get clusterissuer letsencrypt-staging letsencrypt-production
kubectl get certificate --all-namespaces
kubectl -n cert-manager get secret cloudflare-api-token
kubectl -n cert-manager logs deploy/cert-manager --tail=100
```

### Verifier summary block and tests

Successful `pi_node_verifier.sh` runs append a Markdown report to
`/boot/first-boot-report.txt` (or a custom `--log` path). The block captures
inventory details followed by a table of checks:

```markdown
## 2025-01-17T22:48:12Z

* Hostname: `pi-01`
* Kernel: `Linux 6.6.23-v8+`
* Hardware: `Raspberry Pi 5 Model B`

### Verifier Checks

| Check | Status |
| --- | --- |
| cgroup_memory | pass |
| kube_proxy_dataplane | pass |
| k3s_node_ready | pass |

### Migration Steps

_No migration steps recorded yet._
```

Status values map to runtime expectations:

- `pass` — prerequisite satisfied (for example the nftables backend is active).
- `fail` — action required before declaring the node healthy.
- `skip` — probe could not run because a dependency was unavailable (for
  example no kubeconfig on the first control-plane).

Run the Bats suites locally to exercise the CLI without waiting on CI:

```bash
bats tests/pi_node_verifier_output_test.bats
bats tests/pi_node_verifier_json_test.bats
AVAHI_AVAILABLE=1 bats tests/bats/mdns_selfcheck.bats
```

The checks target the end-of-run summary and status semantics, ensuring the
Markdown and JSON exports stay consistent across releases.

## 6. Backups and restore procedures

### Scheduled snapshots

Etcd snapshots are scheduled via the k3s configuration (`0 */12 * * *`) and retained for
twenty-eight iterations. Longhorn additionally manages volume snapshots according to application
policies.

### Off-cluster archive

1. Populate the `longhorn-backup-credentials` secrets (per environment) with real access keys using
   `sops`.
2. Update the S3 bucket and endpoint patches under `clusters/*/patches/longhorn-values.yaml` if the
   defaults change.
3. Validate connectivity:

   ```bash
   kubectl -n longhorn-system exec deploy/longhorn-driver-deployer -- longhorn manager backup ls
   ```

### Ethernet DHCP and embedded etcd recovery

This is a proposed operator-controlled procedure, not an automatic repair or a record of commands
executed during the [October incident](../outages/2026-10-16-ethernet-dhcp-control-plane-recovery.md).
Live qualification is tracked in [#2919](https://github.com/futuroptimist/sugarkube/issues/2919).
Use one cluster at a time. Obtain a recovery window and name the operator who may authorize
membership changes. Ethernet is the supported path here; do not introduce Wi-Fi failover, static
address assignment, an upgrade, an uninstall, or a new cluster bootstrap as an incidental repair.

#### 1. Classify before changing anything

| Observed state | Decision |
| --- | --- |
| API and an etcd majority healthy; addresses agree | No membership reset. Investigate application, DNS, certificate, or monitoring failures independently. |
| Two healthy voting members of the same three-member cluster, one failed member | Preserve the healthy majority. Repair only the failed member using a separately reviewed member-replacement procedure; never run `--cluster-reset` on this path. |
| No healthy majority, but local databases available | Stop and isolate all servers, preserve every database, select one justified seed, then consider the existing-database reset below. |
| Database corruption, uncertain cluster identity/freshness, or no defensible seed | Stop. Assess a verified snapshot and acceptable recovery point with the incident owner. Do not guess or force a new cluster. |

Determine quorum from authenticated etcd endpoint health and membership, not SSH, mDNS, a
successful API request alone, or Ready status. Check every reachable member's cluster/member ID,
peer/client URLs, voter/learner state, term, committed/applied progress, alarms, and endpoint health.
Use a compatible `etcdctl` with verified endpoint and CA/client credentials; K3s does not promise
an installed `etcdctl`. Once those options are configured securely, read-only examples are:

```bash
etcdctl member list --write-out=table
etcdctl endpoint status --cluster --write-out=table
etcdctl endpoint health --cluster
etcdctl alarm list
```

Do not publish their raw output. An unreachable endpoint is a failed check, not permission to
remove it. See the upstream [etcd status checks](https://etcd.io/docs/v3.6/tasks/operator/how-to-check-cluster-status/)
and [membership guidance](https://etcd.io/docs/v3.6/op-guide/runtime-configuration/).
The single-member mechanism in [PR #2914](https://github.com/futuroptimist/sugarkube/pull/2914)
is draft work requiring two surviving healthy members; it is not the all-node recovery procedure.

#### 2. Establish identity and effective configuration

Record cluster/environment, node name, machine identity, installed binary version, service unit,
configuration path, data directory, and current Ethernet address on each server. Keep credentials,
raw addresses, and machine-specific evidence in restricted incident storage. Example local reads:

```bash
k3s --version
k3s server --help
ip -4 -o addr show dev eth0 scope global
systemctl show k3s -p FragmentPath -p DropInPaths -p ActiveState -p NRestarts
```

Privately inspect the unit, its environment files, command arguments, and the running process.
These may contain secrets; do not paste them into an issue. Resolve any alternate `--config`,
`K3S_CONFIG_FILE`, `--data-dir`, node name, server URL, and critical cluster flags. Compare configured
SANs with the intended endpoint; a valid hostname lookup is not certificate or peer-health proof.

The [K3s configuration reference](https://docs.k3s.io/installation/configuration) describes YAML
and command-line precedence. Check base YAML plus alphabetically loaded drop-ins; later keys can
replace earlier ones, and CLI flags override file settings. A foreground recovery invocation does
not automatically inherit a systemd unit's environment or arguments. Build a reviewed, root-only
recovery configuration containing the effective required settings and original identity before
using the templates below. Preserve critical cluster settings across all members.

For incident versions `v1.35.4+k3s1` and `v1.34.5+k3s1`, inspect their respective
[agent flag definitions](https://github.com/k3s-io/k3s/blob/v1.35.4%2Bk3s1/pkg/cli/cmds/agent.go)
and [production definitions](https://github.com/k3s-io/k3s/blob/v1.34.5%2Bk3s1/pkg/cli/cmds/agent.go).
Do not assume `K3S_NODE_IP` or `K3S_FLANNEL_IFACE` is consumed merely because it appears in a
service environment. Use supported YAML/flags and remove conflicting obsolete CLI overrides
under review. This YAML fragment is a template; replace the placeholder with that node's verified
current Ethernet address before use:

```yaml
node-ip: "<CURRENT_ETHERNET_IPV4>"
flannel-iface: eth0
```

It is a recovery-time value, not a durable DHCP update mechanism. Do not copy another node's
address or assume a generated file is effective. Keep the exact installed patch version during
recovery; verify its help/source for every option. Runtime refresh remains tracked in
[#2915](https://github.com/futuroptimist/sugarkube/issues/2915).

#### 3. Preserve evidence and choose a seed

Before any membership reset or peer database move:

1. Confirm each server belongs to the intended cluster. Stop K3s on all servers and verify service
   and process termination. Prevent unattended restarts and automation from starting any peer.
   Account for unreachable servers by isolating them; inability to prove isolation is a stop condition.
2. Preserve a cold copy of each server's effective data directory, token, configuration, service
   definition/drop-ins, certificates, and node identity material with original permissions. Store
   copies outside the directory that will be changed, with access controls and sufficient space.
3. Verify copies can be read, inventories are complete, and checksums match after copying. Record
   timestamps and cluster/node identity. Protect the token separately; it is required to decrypt
   bootstrap data in backups. Neither hashes nor successful archive listing proves a valid restore.
4. Compare the available members' committed/applied progress and history, database health, and last
   known writes. Select one freshest defensible seed and document the basis and recovery-point risk.
   Equal recorded indexes alone do not prove identical contents, latest writes, or correct identity.
   If evidence conflicts or a potentially fresher member is missing, stop for an explicit decision.
5. Preserve application-volume backups independently. Etcd state does not contain all application
   data; a restored Kubernetes object or Bound PVC cannot validate volume contents.

Use the [K3s backup prerequisites](https://docs.k3s.io/datastore/backup-restore) and the exact-version
server help. The following commands are templates for an approved window, not commands to execute
while writing or reviewing this documentation. `RESET_CONFIG` must be an operator-set absolute
path to a separate reviewed root-only reset configuration, with the correct token file, identity,
and data path. Remove `server` from that file and every drop-in it loads; do not pass `--server`.
Use a clean environment for both reset templates below. In both incident versions,
`K3S_CONFIG_FILE` is checked before `--config`, so an inherited value can select another file
and its data directory despite the reviewed argument: see the
[staging config parser](https://github.com/k3s-io/k3s/blob/v1.35.4%2Bk3s1/pkg/configfilearg/parser.go#L167-L181)
and [production config parser](https://github.com/k3s-io/k3s/blob/v1.34.5%2Bk3s1/pkg/configfilearg/parser.go#L167-L181).
Clearing only `K3S_URL` is insufficient. The templates discard all inherited variables, including
`K3S_CONFIG_FILE`, `K3S_DATA_DIR`, token, datastore, S3, debug, and proxy settings. They allow only
a fixed system `PATH`, root `HOME`, and C locale. Put required supported settings explicitly in
`RESET_CONFIG`, including `data-dir`, `token-file`, node identity, and critical cluster flags;
review every loaded drop-in as well. Do not source or forward the service environment wholesale.
If recovery requires a proxy or another environment-only setting, stop and review an explicit
allowlist addition before use; never preserve the caller's environment as a shortcut.

Set `K3S_BINARY` to the verified absolute path of the installed, exact-version K3s executable,
not a shell alias or wrapper that can inject settings. The clean environment is applied after
`sudo`, so variables preserved by sudo policy are discarded before K3s starts. Ensure the effective
reset process has no `K3S_URL`. Both deployed versions reject a reset with a nonempty join URL: see
[staging validation](https://github.com/k3s-io/k3s/blob/v1.35.4%2Bk3s1/pkg/cli/server/server.go#L445-L449)
and [production validation](https://github.com/k3s-io/k3s/blob/v1.34.5%2Bk3s1/pkg/cli/server/server.go#L499-L503).
This requirement applies to both existing-database resets and snapshot restoration, including
when a former joining peer is chosen as seed. Preserve normal reviewed peer join configuration
separately; do not remove peer join targets from the configuration used for sequential rejoin.
Never place a token value on the command line. Do not set reset flags in persistent configuration.

#### 4. Recover exactly one isolated seed

For total quorum loss with a justified usable existing database, stop the service and perform
one membership reset on the selected seed only:

```bash
sudo systemctl stop k3s
sudo /usr/bin/env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  HOME=/root LANG=C "${K3S_BINARY:?set verified absolute K3s binary path}" server \
  --config "${RESET_CONFIG:?set reviewed reset config}" --cluster-reset
```

This resets membership using the existing database; it does not select or restore a scheduled
snapshot. Require a successful completion message and exit before restarting normally. Preserve
failure output privately and stop on errors. Do not bypass the reset safety marker, repeat resets,
or reset a second seed. Confirm persistent service configuration has the same intended settings
and no reset/restore flags or obsolete join target, then start only the seed:

```bash
sudo systemctl start k3s
```

Verify its API, cluster identity, one-member voting configuration, current address and lease before
admitting peers. Do not mistake a fresh empty cluster for recovered state: inspect expected
namespaces and representative pre-incident resources before continuing.

#### 5. Bound Node status convergence

Compare current `eth0` address, effective node IP, Node annotations, and `.status.addresses`
independently. A current annotation does not prove a current InternalIP. With an explicitly selected
`RECOVERY_CONTEXT` and verified `NODE_NAME`, these are read-only examples:

```bash
kubectl --context "${RECOVERY_CONTEXT:?select cluster}" get --raw='/readyz?verbose'
kubectl --context "$RECOVERY_CONTEXT" get node "${NODE_NAME:?select node}" -o json
kubectl --context "$RECOVERY_CONTEXT" -n kube-node-lease get lease "$NODE_NAME" -o yaml
```

Set a bounded observation window before beginning: proposed default is five minutes per node,
checking every 15 seconds, with at most one deliberate restart after a reviewed configuration
correction. These bounds are proposed operating limits, not measured recovery guarantees. Count
unexpected restarts separately. Repeated network-policy interface failures, nonadvancing leases,
or persistent obsolete InternalIP at the deadline require a stop, not a restart loop.

A guarded seed status correction is an exceptional operator decision when the API is available,
configuration and physical identity are proven, and stale status demonstrably blocks startup.
Export the complete Node object privately first. Prepare a JSON Patch that tests both the object
UID and the exact obsolete address before replacing only that InternalIP entry. Preserve Hostname,
ExternalIP, other address families, and all unrelated status. Never replace the whole address list
blindly or patch a peer preemptively. Review the patch against the freshly read object; any failed
test or changed resource requires reassessment. The Kubernetes
[status patch interface](https://kubernetes.io/docs/tasks/manage-kubernetes-objects/update-api-object-kubectl-patch/)
supports a separately targeted status update:

```bash
kubectl --context "$RECOVERY_CONTEXT" patch node "$NODE_NAME" \
  --subresource=status --type=json --patch-file "${REVIEWED_STATUS_PATCH:?review patch first}"
```

This is not a general status ownership fix. Require subsequent kubelet/controller convergence and
fresh leases. If status reverts or the loop persists, stop and retain the evidence for
[#2917](https://github.com/futuroptimist/sugarkube/issues/2917); do not disable network policy as a
shortcut. The reported October peer recovery converged without manual peer status correction.

#### 6. Rejoin preserved peers sequentially

Only after the seed passes its checks, choose one stopped peer with matching identity, exact
version, critical flags, original token, supported Ethernet settings, and a reachable current seed
join endpoint with valid TLS. Keep the other peer isolated. Confirm this peer's cold backup first.
Move its old `server/db` directory to an operator-chosen, nonexisting preserved location outside
the active database path; do not erase it. Verify the destination and ownership before starting.
Do not move the seed's database or discard certificates/token/identity material. The active peer
database must be absent so it can rejoin the recovered membership instead of reopening old state.

Start this peer normally. Verify membership identity, healthy endpoint, learner promotion to voter,
Node address convergence, and advancing leases within the bounded window. Require the seed to
remain healthy. Only then repeat for the final peer. If a peer fails, stop that peer, preserve its
new diagnostics and data, and keep the established members intact. Do not repeatedly remove/add
members, run resets on peers, or start all old databases together.

#### 7. Separate acceptance gates

Record UTC start/end times, sample counts, and evidence location for each gate. The short October
windows do not substitute for a future qualification soak. Proposed acceptance is at least
15 minutes of healthy observations, plus a separately approved longer qualification window under
[#2916](https://github.com/futuroptimist/sugarkube/issues/2916).

| Gate | Required evidence |
| --- | --- |
| API | Authenticated readiness succeeds throughout the observation window. |
| Etcd | Expected three members, three voters, healthy endpoints, no unexpected learners or alarms; progress consistent with activity. |
| Addresses | Ethernet, effective config, Node status, peer/client endpoints and intended join configuration agree; endpoint TLS verifies. |
| Leases and restarts | Each node's lease advances; all services remain active; restart counts stop increasing. |
| Pod networking | Approved existing probes verify cross-node pod traffic, service routing, DNS, and expected network-policy allow/deny behavior. |
| Workloads and storage | Expected deployments/daemonsets ready; jobs interpreted by purpose; storage mounts and application reads/writes validated under separate authorization. |
| Monitoring | New samples after recovery, scrape targets healthy, alert transitions timestamped, watchdog and external probes independently verified. A loading dashboard is insufficient. |
| Applications | Each affected service passes its owner-defined functional check, including chat where applicable; record internal and external results separately. |
| Data | Reconcile representative pre-incident records and acknowledged writes; qualify backup restore in isolation. Record unknowns and possible recovery-point loss. |

Useful read-only inventory complements, but does not replace, the gates:

```bash
kubectl --context "$RECOVERY_CONTEXT" get nodes -o wide
kubectl --context "$RECOVERY_CONTEXT" -n kube-node-lease get leases
kubectl --context "$RECOVERY_CONTEXT" get pods,deployments,daemonsets -A
kubectl --context "$RECOVERY_CONTEXT" get pvc -A
```

#### Stop and rollback rules

Stop on uncertain target/identity, missing token/configuration, unreadable backups, insufficient
space, uncertain freshest seed, inability to isolate peers, TLS failures, unexpected membership,
corruption alarms, status divergence, or failed bounded checks. Keep unaffected healthy members
running when on the healthy-quorum path. During all-node recovery keep unrecovered peers stopped.

Before a reset, a reviewed configuration rollback can restore saved configuration while all
servers remain stopped; validate address correctness before starting anything. After a membership
reset, old peer databases are forensic/recovery assets, not a safe rolling rollback. Do not copy
one back into a running new membership. Preserve the new state too, isolate the cluster, and have
the owner select a coherent recovery point and a new reviewed plan. Retain backups until data
validation and owner acceptance, with monitoring verification tracked in
[#2918](https://github.com/futuroptimist/sugarkube/issues/2918).

### Restoring etcd from snapshots

Snapshot restoration is a separate recovery-point decision. It was not demonstrated by the
October incident. Apply the identity, isolation, backup, configuration, sequential rejoin, and
acceptance gates above. Select a trusted snapshot with its original server token and verify its
provenance, checksum, version compatibility, and expected data age. First qualify the restore in
an isolated environment; obtain explicit acceptance of potential lost writes before live use.

With all servers stopped and exactly one selected seed, the reviewed local-snapshot template is:

```bash
sudo /usr/bin/env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  HOME=/root LANG=C "${K3S_BINARY:?set verified absolute K3s binary path}" server \
  --config "${RESET_CONFIG:?set reviewed reset config}" \
  --cluster-reset --cluster-reset-restore-path "${VERIFIED_SNAPSHOT:?select verified snapshot}" \
  --etcd-s3=false
```

The local path must be absolute. The S3 override prevents inherited remote settings from changing
local snapshot selection. Remote restores need a separately reviewed configuration accessible
without the Kubernetes API; do not put credentials in shell history. After successful completion,
start the seed without reset flags and rejoin peers using the preserved-database procedure above.
Do not simply restart peers with their obsolete databases. Follow the upstream
[K3s reset and restore reference](https://docs.k3s.io/cli/etcd-snapshot) and check exact-version
behavior before use. Restore testing and application-data proof remain open in
[#2919](https://github.com/futuroptimist/sugarkube/issues/2919).

## 7. Promotion flow

1. Pin container images in the `clusters/staging` overlay with immutable digests.
2. After validation, cherry-pick or merge the digest updates into `clusters/prod`.
3. Flux automatically reconciles the changes in production; monitor Grafana dashboards and Loki logs
   to confirm stability.

To temporarily switch to the NFS provisioner, build the storage overlay and include
`platform/storage/overlays/nfs/longhorn-suspend.yaml` so that Longhorn is paused while the external
provisioner becomes the default StorageClass.

## 8. Maintenance tasks

- Rotate age keys by updating `.sops.yaml` and re-encrypting secrets with
  `just seal-secrets env=<env>`.
- Keep `scripts/flux-bootstrap.sh` executable and rerun `just flux-bootstrap env=<env>` after Flux
  upgrades.
- If MetalLB is introduced, follow the comments in the k3s config examples to disable `servicelb`.
