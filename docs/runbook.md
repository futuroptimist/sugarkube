# Sugarkube platform runbook

This runbook documents the happy-path for bootstrapping and operating the Pi 5 backed
k3s HA platform across dev, int, and prod. Each high-level task also includes the
low-level manual procedure for verification and debugging.

## Prerequisites
- Three Raspberry Pi 5 servers with NVMe storage per environment.
- Ubuntu 22.04 LTS or Raspberry Pi OS Lite 64-bit with `k3s` packages uninstalled.
- Shared GitOps repository cloned to an operator workstation with `kubectl`, `flux`,
  `sops`, and `age` installed.
- Control-plane nodes connected to the same L2 segment as the kube-vip virtual IPs.

## 1. Bootstrap the first server

### High-level (`just`)
```bash
just platform-bootstrap env=dev  # runs after OS preparation and k3s install
```

### Low-level steps
1. Copy `docs/k3s/config-examples/server-first.yaml` to `/etc/rancher/k3s/config.yaml`.
2. Populate `${K3S_TOKEN}` with a shared secret for the entire cluster.
3. Review optional S3 snapshot offload values and ensure corresponding SOPS secrets
   exist (`platform/secrets/s3-snapshot-offload.enc.yaml`).
4. Start k3s: `sudo systemctl enable --now k3s`.
5. Confirm the control-plane is healthy: `sudo k3s kubectl get nodes -o wide`.

## 2. Deploy kube-vip on the first server

### High-level (`just`)
`just platform-bootstrap env=dev` also applies the Flux manifests that deploy kube-vip.

### Low-level steps
1. Export the VIP defined in `clusters/<env>/patches/kube-vip.yaml` to your notes.
2. Verify kube-vip DaemonSet is running on the control-plane nodes:
   ```bash
   sudo k3s kubectl get pods -n kube-system -l app.kubernetes.io/name=kube-vip
   ```
3. Ensure the virtual IP responds to ARP on the management network.

## 3. Join additional servers

### High-level (`just`)
No dedicated recipe; repeat OS preparation and use the shared `just cluster-up` helper
if desired.

### Low-level steps
1. Copy `docs/k3s/config-examples/server-join.yaml` to `/etc/rancher/k3s/config.yaml` on
   each joining server and adjust the `server:` field if using the int or prod VIP.
2. Use the same `${K3S_TOKEN}` and restart k3s: `sudo systemctl enable --now k3s`.
3. Confirm three servers are present and Ready: `sudo k3s kubectl get nodes`.

## 4. Bootstrap Flux

### High-level (`just`)
```bash
just platform-bootstrap env=<env>
```
This wraps `scripts/flux-bootstrap.sh` and wires the Git repository to Flux.

### Low-level steps
1. Place your age private key at `.age.key` in the repository root.
2. Apply the Flux components and sync manifests:
   ```bash
   kubectl apply -k flux
   flux create source git sugarkube \
     --namespace flux-system \
     --url <git-url> \
     --branch main \
     --interval 1m \
     --export | kubectl apply -f -
   flux create kustomization platform \
     --namespace flux-system \
     --source GitRepository/sugarkube \
     --path ./clusters/<env> \
     --prune true \
     --interval 5m \
     --decryption-provider sops \
     --decryption-secret sops-age \
     --export | kubectl apply -f -
   ```
3. Wait for controllers to report Ready: `kubectl -n flux-system get deployments`.

## 5. Platform reconciliation

### High-level (`just`)
The Flux bootstrap recipe continuously reconciles the `clusters/<env>` kustomization.

### Low-level checks
- Validate `kube-system/kube-vip` pods are running on all servers.
- Ensure `cert-manager`, `cloudflared`, Longhorn (or NFS overlay), Prometheus, Grafana,
  Alertmanager, Loki, and Promtail pods are ready.
- Confirm network policies are enforced:
  ```bash
  kubectl get networkpolicies -A
  ```

## 6. Backups and restore

### Scheduled snapshots
- Snapshot schedule and retention are defined in the server configs. Verify with:
  ```bash
  sudo journalctl -u k3s | grep snapshot
  ```
- To offload snapshots to S3, decrypt `platform/secrets/s3-snapshot-offload.enc.yaml`,
  configure the endpoint, and uncomment the `etcd-s3` options in the k3s configs.

### Restoring etcd
1. Stop k3s on all servers: `sudo systemctl stop k3s`.
2. Choose a snapshot (local or S3) and copy it to the restoring node.
3. Run `k3s server --cluster-reset --cluster-reset-restore-path <snapshot>` once.
4. Remove the reset flag from `/etc/systemd/system/k3s.service` if added, then start k3s.
5. Rejoin the other servers after the restored leader is healthy.

## 7. Promotion workflow
- Pin application and platform images via immutable digests in `clusters/int`.
- Validate in int, then merge the digest updates into `clusters/prod`.
- Flux reconciles prod automatically after the merge.

## 8. Upgrades
- Upgrade k3s nodes one at a time using the upstream guidance.
- Allow Flux to apply HelmRelease upgrades; watch `flux get hr -A` for status.
- Pause HelmRelease reconciliation if a manual maintenance window is required:
  `flux suspend hr <release> -n <namespace>`.

## 9. Troubleshooting tips
- Decrypt secrets locally with `sops -d platform/secrets/<secret>.enc.yaml`.
- Inspect Flux events: `flux events --for Kustomization/sugarkube-cluster`.
- For cloudflared, use `kubectl logs -n cloudflared deploy/cloudflared` to confirm
  tunnel registration.
