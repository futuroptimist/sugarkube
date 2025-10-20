# Sugarkube Platform Runbook

This runbook describes how to bootstrap and operate the Raspberry Pi 5 backed
k3s high-availability platform. The happy path uses `just` recipes where
possible. A corresponding low-level breakdown follows each macro step so you can
validate behaviour or debug failures in the field.

## Prerequisites

- Three Raspberry Pi 5 servers per environment with NVMe storage attached via
  the M.2 HAT+.
- Ubuntu 22.04 or Raspberry Pi OS Bookworm 64-bit on every node.
- SSH access with passwordless sudo for the provisioning operator.
- A Cloudflare account with API token permissions for DNS updates and tunnel
  management.
- An S3-compatible object store (Cloudflare R2, MinIO, etc.) for etcd snapshot
  offload.
- A workstation with `kubectl`, `kustomize`, `flux` CLI, `sops`, `age`, and
  `just` installed.

## Step 1 – Bootstrap the first server

### High-level

```bash
sudo just up env=dev
```

### Low-level

1. Flash the base operating system using the procedures in `scripts/`.
2. Configure `/etc/rancher/k3s/config.yaml` on the first server using
   `docs/k3s/config-examples/server-first.yaml` as a template.
3. Set the shared `K3S_TOKEN` in `/var/lib/rancher/k3s/server/token` or via the
   `K3S_TOKEN` environment variable when running the installation script.
4. Install k3s: `curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION=<channel>
   sh -s - server --config /etc/rancher/k3s/config.yaml`.
5. Confirm the API server is reachable via the kube-vip virtual IP once flux has
   reconciled the DaemonSet.

## Step 2 – Join the remaining control-plane nodes

### High-level

```bash
sudo just up env=dev SUGARKUBE_SERVERS=3
```

### Low-level

1. Copy the shared token and `/etc/rancher/k3s/config.yaml` template from
   `docs/k3s/config-examples/server-join.yaml` to each additional node.
2. Install k3s with the `server --server https://10.0.0.40:6443` flag so each
   node joins via the kube-vip virtual IP.
3. Verify embedded etcd forms a three-member cluster: `sudo k3s kubectl get
   nodes` and `sudo k3s etcdctl member list`.
4. Confirm the `node-role.kubernetes.io/control-plane` taint is present (see
   `docs/k3s/config-examples/server-taints.md`).

## Step 3 – Bootstrap Flux and GitOps

### High-level

```bash
just flux-bootstrap env=dev \
  FLUX_REPO_URL=ssh://git@github.com/example/sugarkube-platform.git \
  FLUX_REPO_BRANCH=main
```

Export `SOPS_AGE_KEY_FILE=/path/to/age.key` before running the recipe so SOPS
can decrypt the committed secrets.

### Low-level

1. Create the `flux-system` namespace if it does not exist.
2. Apply the controllers from `flux/gotk-components.yaml`: `kustomize build
   flux | kubectl apply -f -`.
3. Create the `sops-age` secret: `kubectl -n flux-system create secret generic
   sops-age --from-file=age.agekey=$SOPS_AGE_KEY_FILE`.
4. Create the Git source and Kustomization definitions from
   `flux/gotk-sync.yaml` (update the repository URL and branch).
5. Wait for the `flux-system` Kustomization to reconcile successfully.

## Step 4 – Platform reconciliation

Flux applies the shared stack under `platform/` and the environment overlays in
`clusters/<env>/`. Monitor progress with `flux get kustomizations` and the
FluxUI dashboards under Grafana once the observability stack is online.

Key components:

- **kube-vip** exposes the control-plane virtual IP in ARP mode across the three
  servers.
- **cert-manager** issues certificates using the Cloudflare DNS-01 solver with
  staging and production `ClusterIssuer` resources.
- **cloudflared** publishes Traefik via a Cloudflare Tunnel without opening WAN
  ports. A tunnel secret per environment is managed via SOPS.
- **external-dns** is available as an opt-in component under
  `platform/networking/external-dns/`. Add it to an environment by listing the
  component in the relevant `kustomization.yaml`.
- **Longhorn** provides the default `longhorn` StorageClass. Use the optional
  `platform/storage/components/nfs` component to swap to NFS.
- **kube-prometheus-stack**, **Loki**, and **promtail** deliver metrics and
  log aggregation for the platform namespaces.
- NetworkPolicies enforce default deny rules for kube-system, ingress-system,
  and monitoring while allowing platform traffic and egress to the internet.

## Step 5 – Backups and restores

### Scheduled snapshots

- Embedded etcd snapshots run twice per day per the k3s configuration examples.
- Flux deploys the `etcd-s3-credentials` secret for each environment. Reference
  it by enabling `etcd-s3` options in `/etc/rancher/k3s/config.yaml` to push
  snapshots to your S3-compatible store.

### Manual backup

```bash
sudo k3s etcd-snapshot save --name $(date +%Y%m%d-%H%M)-manual.db
```

### Restore procedure

1. Stop k3s on all three servers: `sudo systemctl stop k3s`.
2. Copy the desired snapshot to `/var/lib/rancher/k3s/server/db/snapshots/` on
   each server.
3. Run `sudo k3s server --cluster-reset --cluster-reset-restore-path <snapshot>`
   on the first server.
4. Remove the `--cluster-reset` line after the node reports success, then start
   the service normally.
5. Start k3s on the remaining servers and confirm etcd convergence.

## Step 6 – Promotion workflow

1. Pin container images by digest in the `clusters/int/` overlay.
2. Validate the change in the integration cluster.
3. Promote by merging the digest updates into `clusters/prod/` via Git. Flux
   reconciles the production environment automatically.

## Observability

- Grafana dashboards become available via the Cloudflare tunnel once DNS is in
  place.
- Loki receives logs from promtail (running as a DaemonSet on every node).
- Alertmanager starts with default routing; extend alerts via Helm values under
  `platform/observability/kube-prometheus-stack/`.

## Troubleshooting

- `flux logs --all-namespaces` surfaces reconciliation errors.
- `kubectl -n cloudflared logs deploy/cloudflared` for tunnel issues.
- Use `kubectl describe networkpolicy -n kube-system` to confirm enforcement.
- Disable the default deny NetworkPolicy temporarily by deleting it if you need
  to run emergency diagnostics (remember to reapply with
  `kustomize build platform/network-policies | kubectl apply -f -`).

## Upgrades

1. Stage changes in `clusters/dev/`.
2. Let Flux apply and verify via dashboards.
3. Cherry-pick or merge into `clusters/int/` and finally `clusters/prod/` when
   ready.
4. For k3s upgrades, repeat the install script with the target channel.

## Appendix – Manual flux uninstall

If you ever need to uninstall Flux, run:

```bash
flux uninstall --silent
kubectl delete namespace flux-system
```

Ensure Git automation is paused before removing controllers to avoid drift.
