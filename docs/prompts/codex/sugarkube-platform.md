# One-click repo task: bootstrap a Pi5-backed k3s HA platform (prod/staging/dev) with GitOps

You are a senior platform engineer. Implement the following in this repo **in one atomic PR**.

## Context
- Hardware: Raspberry Pi 5 (3 nodes per env), each with NVMe via M.2 HAT+.
- Cluster topology (ALL ENVS): **k3s HA with embedded etcd** using **three server nodes**; optional
  workers may be added later.
- Control-plane VIP: **kube-vip** in ARP/L2 so agents join via a stable API endpoint.
- Ingress & exposure: keep k3s **Traefik**; terminate TLS via **cert-manager** (DNS‑01 Cloudflare);
  publish through **cloudflared** (Cloudflare Tunnel) to avoid opening WAN ports. `external-dns`
  for Cloudflare is optional.
- Storage: default to **Longhorn** (works on arm64); allow a toggle to use
  **nfs-subdir-external-provisioner**.
- Observability: **kube-prometheus-stack** (Prometheus/Alertmanager/Grafana) + **Loki** for logs.
- GitOps & secrets: **Flux** drives all deployments; **SOPS/age** for secrets.
- Backups: enable **scheduled etcd snapshots** and include S3-compatible offload config
  (values-only; no credentials in plain text).
- Networking notes: If we run MetalLB later, disable ServiceLB in k3s server flags across all
  servers.

## Deliverables
1. **Repo layout (kustomize + Flux)**
   - Create:
     - `clusters/prod/`, `clusters/staging/`, `clusters/dev/`
     - `platform/` (shared stack: kube-vip, traefik config, cloudflared, cert-manager, issuers,
       external-dns [optional], storage, monitoring)
     - `apps/` (left empty here; app repos own their charts)
     - `infra/` (bootstrap helpers)
   - Each env directory contains `kustomization.yaml` that composes `platform/` and env-specific
     overlays (hostnames, cert issuers, tunnel names, image policies, etc.).

2. **Flux bootstrap manifests**
   - Add `flux/` with `gotk-components.yaml`, `gotk-sync.yaml` and decryption stanza for SOPS/age.
   - Create `scripts/flux-bootstrap.sh` with idempotent bootstrap steps and comments.

3. **SOPS/age integration**
   - Add `.sops.yaml` at repo root with AGE recipients.
   - Place **sample encrypted** secrets for:
     - Cloudflare API Token (DNS‑01)
     - cloudflared Tunnel credentials (JSON)
     - GHCR read credentials (if needed)
     - S3 snapshot offload (endpoint/keys)
   - Do **NOT** commit any plaintext secrets.

4. **Platform stack (Helm/HelmRelease or Kustomize)**
   - `kube-vip`: control-plane VIP for k3s servers (DaemonSet on masters). Provide values for ARP/L2;
     VIP is env-specific.
   - `cert-manager` + `ClusterIssuer` (Let’s Encrypt staging + prod) using **Cloudflare DNS‑01** via
     API Token Secret.
   - `cloudflared` (Helm): route public hostnames to Traefik; the tunnel Secret comes from SOPS.
   - `external-dns` (optional): Cloudflare provider; off by default behind a Kustomize overlay flag.
   - Storage:
     - Default: **Longhorn** Helm chart + a `StorageClass` named `longhorn` as default.
     - Alternate overlay: **nfs-subdir-external-provisioner** with an env-specific NFS server/path.
   - Observability:
     - **kube-prometheus-stack** (with minimal values), **Loki** (single‑binary or simple‑scalable)
       + Promtail/Alloy DaemonSet.
   - Network policy: provide a default `deny-all` and a `platform-allow` set for
     kube-system/monitoring/ingress.

5. **k3s server configuration examples**
   - Add `docs/k3s/config-examples/` with:
     - `server-first.yaml` (cluster-init; tls-san includes VIP; **disable ServiceLB** if MetalLB is
       used later; etcd snapshot schedule & retention; S3 offload placeholders)
     - `server-join.yaml` (join via VIP; same critical flags as first server)
   - Include a `server-taints.md` note showing how to taint control-plane nodes (`NoSchedule`) if we
     want to keep them workload-free.

6. **Runbook & acceptance**
   - `docs/runbook.md`: first server bootstrap → kube‑vip → join 2nd/3rd servers → Flux bootstrap →
     platform reconcile → restore/backup procedures for etcd.
   - `docs/prompts/codex/sugarkube-platform.md`: keep THIS prompt + the acceptance checklist below.

## Acceptance checklist
- [ ] k3s HA topology documented and reflected in `server-first.yaml` / `server-join.yaml` (three
      servers with embedded etcd, join via kube‑vip VIP).
- [ ] kube‑vip deployed; API reachable via VIP; agents can join using VIP.
- [ ] Flux bootstraps and reconciles: Traefik, cert‑manager (+ ClusterIssuer), cloudflared; optional
      external‑dns gated by overlay.
- [ ] Default StorageClass present (Longhorn) and binds PVCs on arm64; NFS overlay works with env
      vars for server/path.
- [ ] kube‑prometheus‑stack + Loki up; sample dashboards/logs visible.
- [ ] SOPS/age in place; no plaintext secrets; Cloudflare token and tunnel creds stored encrypted;
      GHCR creds if needed.
- [ ] etcd snapshots scheduled; retention set; S3 offload values wired (no creds in clear).
- [ ] NetworkPolicies applied (default deny + platform allow).
- [ ] `docs/runbook.md` covers bootstrap, upgrades, backup/restore, and promotion (see Flux notes
      below).
- [ ] `clusters/{dev,staging,prod}` overlays differ only where needed (hostnames, VIPs, tunnel
      name, issuers).

## Notes
- Promotion model: pin container images by immutable digest, then **promote** by merging the pinned
  digest from `staging` → `prod` (Flux will reconcile).
- Leave Traefik enabled in k3s unless there’s a hard requirement to swap to NGINX; if you later adopt
  MetalLB, ensure `--disable=servicelb` on **all** k3s servers.

Ensure we keep our happy path as high-level as possible, using `just` recipes to abstract away as
much as possible. For every high level abstraction, make sure there's an equivalent doc showing the
low-level procedure, both for correctness verification and for debugging.
