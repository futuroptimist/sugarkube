# Sugarkube Pi5 k3s Platform Runbook

This runbook covers day-one bootstrap through ongoing operations for the Pi5-backed k3s HA
platform. High level flows use the `just` targets introduced with this change; every section
also lists the equivalent low-level steps for verification and debugging.

## 1. Bootstrap prerequisites

**High level**

```bash
just prereqs
```

**Low level**

1. Update APT cache: `sudo apt-get update`.
2. Install Avahi, mdns and utilities: `sudo apt-get install -y avahi-daemon avahi-utils libnss-mdns curl jq`.
3. Enable Avahi for discovery: `sudo systemctl enable --now avahi-daemon`.
4. Ensure `/etc/nsswitch.conf` contains `mdns4_minimal` ahead of `dns`.

## 2. First control-plane node

**High level**

```bash
sudo install -d /etc/rancher/k3s
sudo tee /etc/rancher/k3s/config.yaml < docs/k3s/config-examples/server-first.yaml
sudo systemctl enable --now k3s
```

**Low level**

1. Copy the `server-first.yaml` template and replace placeholders (token, VIP, S3 settings).
2. Make sure `cluster-init: true` is present on the first node only.
3. Confirm `tls-san` entries include the kube-vip VIP and desired hostnames.
4. Start the service: `sudo systemctl enable --now k3s`.
5. Verify etcd is healthy: `sudo k3s etcd-snapshot ls`.

## 3. kube-vip health check

**High level**

The DaemonSet is deployed through Flux (see section 5). After k3s starts, wait for kube-vip to
bind the VIP (`10.0.0.40` in dev) by watching `ip addr`.

**Low level**

1. Manually deploy the manifest for smoke testing if needed: `kubectl apply -k platform/kube-vip`.
2. Confirm leader election: `kubectl logs -n kube-system ds/kube-vip`.
3. Ping the VIP from another node to verify ARP advertisement.

## 4. Join the second and third control-plane nodes

**High level**

```bash
sudo install -d /etc/rancher/k3s
sudo tee /etc/rancher/k3s/config.yaml < docs/k3s/config-examples/server-join.yaml
sudo systemctl enable --now k3s
```

**Low level**

1. Update the `server` field to `https://<vip>:6443`.
2. Remove `cluster-init`.
3. Start the service and verify registration: `sudo k3s kubectl get nodes`.
4. Apply taints per `docs/k3s/config-examples/server-taints.md`.

## 5. Flux bootstrap and GitOps sync

**High level**

```bash
just platform-bootstrap env=dev git_url=ssh://git@github.com/example/sugarkube-platform.git
```

**Low level**

1. Create the `flux-system` namespace: `kubectl create namespace flux-system`.
2. Install controllers: `flux install --namespace flux-system --components-extra image-reflector-controller,image-automation-controller --export | kubectl apply -f -`.
3. Apply repo manifests: `kubectl apply -f flux/gotk-components.yaml` and `kubectl apply -f flux/gotk-sync.yaml`.
4. Configure the Git secret via `flux create secret git ... --export | kubectl apply -f -`.
5. Patch the GitRepository and Kustomization with the target URL, branch and `clusters/<env>` path.
6. Create the `sops-age` secret by decrypting `secrets/flux-system/sops-age.enc.yaml` locally and
   applying the plaintext.
7. Trigger a reconcile: `flux reconcile source git flux-system -n flux-system --with-source`.

## 6. Platform reconciliation expectations

Flux applies the shared stack from `platform/` plus the environment overlays in `clusters/<env>/`.
Checkpoints:

- `kube-vip` DaemonSet ready on all control-plane nodes.
- `cert-manager` with staging and production issuers referencing the Cloudflare token secret.
- `cloudflared` Deployment tunnelling Traefik to Cloudflare (`cloudflared` namespace).
- `longhorn` operators ready (`longhorn-system` namespace) and the `longhorn` StorageClass marked
  default. For NFS-based clusters, switch to the overlay documented below.
- `kube-prometheus-stack` and `loki` running in `monitoring`, with Grafana served through the
  Cloudflare tunnel and Promtail shipping logs.
- NetworkPolicies `default-deny` and `platform-allow` present in `kube-system` and `monitoring`.

## 7. Switching storage backends

**High level**

Use the NFS overlay for clusters that should mount a central NAS:

```bash
kustomize build platform/storage/nfs | kubectl apply -f -
```

**Low level**

1. Patch the HelmRelease values with the target `nfs.server` and `nfs.path`.
2. Ensure the NFS export allows the Pi subnet and provides no_root_squash.
3. Apply the overlay before workloads claim volumes.

## 8. Backups and restores

- Scheduled etcd snapshots run every 12 hours with retention of 5 copies.
- S3 offload uses the encrypted secret in `secrets/storage/etcd-s3.enc.yaml`.

**Restore flow**

1. Copy the desired snapshot to a local path or S3.
2. Stop k3s on all control-plane nodes: `sudo systemctl stop k3s`.
3. Restore using `k3s server --cluster-reset --cluster-reset-restore-path <snapshot>` on one node.
4. Restart other nodes pointing at the same VIP once the restored node is healthy.

## 9. Observability verification

- Grafana credentials are sourced from the `grafana-admin` secret (rotate via SOPS).
- Loki single-binary stores data under `/var/loki/chunks` on Longhorn-backed PVCs.
- Prometheus retention is 24 hours by default; adjust through the HelmRelease patch.

## 10. Promotion workflow

1. Pin application images by digest in the `int` environment.
2. Merge the digest bump into `prod` to promote.
3. Flux reconcilers roll out the promoted digest.

## 11. Cloudflared troubleshooting

- Credentials live in `cloudflared-tunnel-credentials` (SOPS encrypted).
- Check tunnel status: `kubectl logs deploy/cloudflared -n cloudflared`.
- Run `cloudflared tunnel info` with the same credential JSON for external verification.

## 12. External DNS (optional)

Enable the overlay by adding `platform/external-dns` to the environment kustomization or by
applying it manually:

```bash
kustomize build platform/external-dns | kubectl apply -f -
```

Remember to scope `domainFilters` and rotate the Cloudflare API token if DNS updates fail.
