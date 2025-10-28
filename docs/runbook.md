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

Sugarkube's absence gate follows RFC 6762 guidance: after `just wipe`, the helper demands two
consecutive "not found" responses from Avahi and, when `SUGARKUBE_MDNS_WIRE_PROOF=1`, a short
tcpdump confirming that no port 6443 announcements remain on the wire. This double-negative protects
against stale advertisements being cached elsewhere on the subnet.

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

Replace `dev` with `int` or `prod` for the target environment. `flux-bootstrap` wraps
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

### Discovery guardrails & debugging toggles

- **Readiness gate:** `mdns_selfcheck.sh` refuses to mark a control-plane advertisement as confirmed
  until the kube-apiserver answers on port 6443. The helper cycles through the `.local` hostname and
  resolved IPs, opening sockets until one succeeds, which keeps mDNS truthful during Flannel's
  default overlay setup.
- **Environment toggles:**
  - `SUGARKUBE_MDNS_DBUS=1` (default) leans on Avahi's D-Bus API for deterministic discovery;
    forcing it to `0` reverts to the CLI fallback when the bus is unavailable.
  - `SUGARKUBE_DEBUG_MDNS=1` dumps the browse/resolve traces so you can see exactly how Avahi and
    tcp readiness checks behave.
  - `SUGARKUBE_MDNS_WIRE_PROOF=1` (default outside containers) captures a brief multicast DNS trace
    to prove that announcements really leave the host; set it to `0` if `tcpdump` is blocked.
- **Interpreting `ms_elapsed`:** The field printed in `mdns_selfcheck` and `mdns_absence_gate` logs
  is the end-to-end duration of the discovery attempt. On a quiet LAN with the default Flannel
  backend, expect presence confirmations in ~120–400 ms and absence gates in ~1.5–3.0 s. Larger
  numbers usually signal retransmits or congestion.

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

1. Pin container images in the `clusters/int` overlay with immutable digests.
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
