# Sugarkube Platform Runbook

This runbook documents the expected flow for bringing a three-node Raspberry Pi 5 k3s cluster
online, keeping it healthy, and restoring service after failures. All commands assume an
operator workstation with the `just`, `flux`, `kubectl`, and `sops` CLIs installed.

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

4. Confirm the embedded etcd cluster is healthy:

   ```bash
   sudo k3s etcdctl endpoint status --cluster --write-out=table
   ```

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

Replace `dev` with `staging` or `prod` for the target environment. `flux-bootstrap` wraps
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

### Restoring etcd from snapshots

1. Stop k3s on all control-plane nodes.
2. Copy the desired snapshot from `/var/lib/rancher/k3s/server/db/snapshots` or download it from the
   remote S3 bucket.
3. Restore the snapshot on a single control-plane node:

   ```bash
   sudo k3s server \
     --cluster-init \
     --cluster-reset \
     --cluster-reset-restore-path /var/lib/rancher/k3s/server/db/snapshots/<snapshot>
   ```

4. Remove the reset flags from `/etc/rancher/k3s/config.yaml`, restart k3s on the remaining nodes,
   and confirm the etcd members rejoin.

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
