# Sugarkube: Cluster Rollout & App Migrations Plan

> Purpose: a concise, executable plan to (1) finish Sugarkube on the Pi cluster, then (2) migrate **token.place** and **DSPACE (v3)**, (3) add static hosting for **danielsmith.io**, and (4) containerize+deploy **jobbot3000**. This is written to be evergreen and idempotent—safe to re-run as the cluster evolves.

---

## 0) Objectives & Success Criteria

**Objectives**
- Bring up a stable k3s-based cluster (“Sugarkube”) with GitOps, TLS, ingress, metrics, logging, and storage.
- Standardize container build/publish for ARM64 and AMD64.
- Ship Helm/Kustomize scaffolds for each app, with the same conventions (namespaces, probes, resource limits, secrets, SVC/Ingress).
- Move token.place and DSPACE onto the cluster; stand up static hosting for danielsmith.io; run jobbot3000 (frontend + backend) in the cluster.

**Definition of Done**
- One GitOps repo controls the entire cluster.
- `kubectl get nodes`, `get kustomizations`, `get helmreleases`, `get certificates` all healthy.
- Ingress + TLS terminate correctly; apps reachable by DNS.
- Monitoring dashboards show all app pods and Ingress traffic; on-call smoke check passes.
- Persistent data (if any) survives a rolling upgrade.

---

## 1) Baseline & Assumptions

- Raspberry Pi nodes (64‑bit OS), k3s installed (server + agents).
- Container runtime: containerd (k3s default).
- Private container registry available (GHCR).
- DNS managed by Cloudflare; we can use DNS‑01 for TLS and optionally Cloudflare Tunnels for external access.
- GitHub Actions for builds.

---

## 2) Reference Architecture (Sugarkube)

### Control plane & GitOps
- **k3s** as the lightweight Kubernetes distribution.
- **Flux** GitOps controller manages all cluster state (infra + apps) via Kustomize overlays.
- Layout:
  ```
  cluster/
    flux-system/          # bootstrap manifests
    infra/                # cert-manager, ingress-controller, LB, storage, monitoring
      base/
      overlays/prod/
    apps/
      token-place/
      dspace/
      danielsmith-io/
      jobbot3000/
  ```
- Principle: “everything declarative”; no `kubectl apply` in day‑to‑day.

### Networking, Ingress, TLS, DNS
- **Ingress**: NGINX Ingress Controller (or Traefik if retaining k3s default).
- **TLS**: cert-manager + Let’s Encrypt (DNS‑01 solver for Cloudflare).
- **DNS automation** (optional): ExternalDNS manages Cloudflare records from Ingress objects.
- **Exposure options**
  - **LAN:** MetalLB allocates `LoadBalancer` IPs.
  - **Public w/o NAT:** Cloudflare Tunnel (`cloudflared`) terminating at the cluster Ingress.

### Storage
- Start with **Local Path Provisioner** (default in k3s).
- Add **Longhorn** for replicated block storage when you need durability/resilience.

### Observability
- **kube‑prometheus‑stack** (Prometheus Operator + Grafana + Alertmanager).
- Dashboards + alerts for pod restarts, 5xx at ingress, cert expiry, CPU throttling.

### Images & Registry
- **Multi‑arch** builds with Docker Buildx (`linux/amd64,linux/arm64`).
- Publish to **GHCR** with immutable tags and semver channels (`:vX.Y.Z`, `:vX`, `:latest` per branch).

### Secrets
- Prefer **sealed, declarative** secrets:
  - `sealed-secrets` or `SOPS` for at‑rest encryption in Git.
  - Keep tokens out of plain manifests; document the decryption path for local ops.

---

## 3) Foundation Workstream (Sugarkube)

1. **Flux bootstrap**
   - Repo: `sugarkube` or a dedicated `sugarkube-cluster`.
   - `flux bootstrap github …` to create `flux-system`.
   - Commit policies: all changes flow through PRs; no out‑of‑band `kubectl`.

2. **Ingress & TLS**
   - Install `ingress-nginx` via `HelmRelease` in `infra/base`, expose as `LoadBalancer` (MetalLB) or as `ClusterIP` behind Cloudflare Tunnel.
   - Install `cert-manager` + `ClusterIssuer` for Let’s Encrypt (staging + prod) with a Cloudflare DNS‑01 token stored as a sealed secret.
   - Set a default `ingressClassName` for apps.

3. **DNS**
   - Optionally install `external-dns` configured for Cloudflare; scope to your domains/namespaces.

4. **Load Balancer**
   - Install **MetalLB** with an IPAddressPool on your LAN (e.g., `192.168.1.240-192.168.1.250`), or skip when using Cloudflare Tunnel exclusively.

5. **Storage**
   - Verify default `local-path` StorageClass exists.
   - If needed, deploy **Longhorn**; define a `longhorn` StorageClass and migrate stateful apps as appropriate.

6. **Observability**
   - Deploy `kube-prometheus-stack`.
   - Seed Grafana dashboards; add alerts for `cert_expiration < 15d`, `Ingress 5xx`, `CPUThrottle`, `RestartBurst`.

7. **Preflight checks**
   ```sh
   kubectl get nodes -o wide
   kubectl -n ingress-nginx get svc
   kubectl -n cert-manager get certificate,clusterissuer
   kubectl -n monitoring get pods
   ```
   - Confirm an example `echo-server` Ingress returns **200 + valid TLS**.

---

## 4) App Workstreams

### A) token.place (relay + backend)
- **Containers**
  - Build `relay` (Python) and `api` separately; add readiness/liveness probes.
  - Publish as multi‑arch to GHCR.
- **Helm chart**
  - Two `Deployments`: `relay`, `api` (ClusterIP each).
  - One `Ingress` host per surface (`relay.token.place`, `api.token.place`).
  - `ConfigMap` for non‑secret config; `Secret` for tokens with projected volume env.
- **Policies**
  - `requests/limits` tuned for Pi (e.g., 100–250m CPU, 128–512Mi RAM per pod).
  - Centralized retry budgets and timeouts (env).

### B) DSPACE v3 (frontend + backend)
- **Frontend**
  - Static build (Vite) → serve via `nginx` image or a shared `web-static` base.
  - Cache policy: long‑TTL for assets, short for HTML.
- **Backend**
  - ClusterIP service; expose only via Ingress path (e.g., `/api`).
- **State**
  - PVC for content/quest data if needed; start with `local-path`, move to `longhorn` for durability.
- **Ingress**
  - `dspace.example.com` → frontend; `/api` → backend service.

### C) danielsmith.io (static site hosting)
- **Two options**
  - **Containerized static**: built site packaged as an Nginx image with `COPY dist/ /usr/share/nginx/html`.
  - **Artifact + sidecar**: mount a ConfigMap or PVC of static files into a minimal web server.
- **Sugarkube template**
  - Reusable Helm subchart `sites/` with values: `host`, `image/tag`, `path`, `cache`, `ingressClass`, `tls`.
- **Exposure**
  - Use ExternalDNS or a Cloudflare Tunnel route to expose the host.

### D) jobbot3000 (frontend + backend)
- **Split services**
  - `frontend`: static build served by Nginx.
  - `backend`: Node service (Fastify/Express).
- **Config**
  - Typed env loader; feature flags to switch connectors (mock vs real).
- **Ingress**
  - Host `jobs.example.com` with `/api` → backend, `/` → frontend.
- **Testing**
  - Add Playwright smoke in CI against a preview namespace.

---

## 5) Standardized Build & Deploy

### CI (GitHub Actions) – Multi‑arch build
- Use Buildx to build `linux/amd64,linux/arm64`.
- Tag scheme:
  - Branch builds: `:sha-<short>` + `:edge`
  - Releases: `:vX.Y.Z` + `:vX` + `:latest`
- Push to GHCR with `GITHUB_TOKEN` permissions.
- Optional: SBOM/provenance for supply‑chain audit.

### CD (Flux)
- **Image automation**
  - Flux `ImageRepository` + `ImagePolicy` to auto‑bump tags matching semver.
  - Kustomize overlays pin image tags; Flux updates when new versions meet policy.
- **Environments**
  - `overlays/dev` (cluster‑internal), `overlays/prod` (public), differing in Ingress class, resources, and HPA.

---

## 6) Security, Reliability, and SLOs

- **Secrets**: sealed-secrets (or SOPS); rotate tokens quarterly.
- **Network**: default deny with NetworkPolicies where practical; allow only required egress.
- **TLS**: Let’s Encrypt prod; staging issuer for dry‑runs; short `renewBefore`.
- **Backups**: if Longhorn used, enable scheduled snapshots/backups; document restore.
- **SLOs**:
  - Ingress success rate ≥ 99.5%, median TTFB < 300ms for static; < 700ms for dynamic.
  - Error budget tracked in Grafana.
- **Runbooks**:
  - Renew/replace certs; restart ingress; roll back via Git revert.

---

## 7) Migration Order & Milestones

1. **M0 — Foundation**: Flux, Ingress, cert-manager, (MetalLB or Tunnel), monitoring, storage check.
2. **M1 — token.place**: api + relay green; tests pass; public host live.
3. **M2 — DSPACE v3**: frontend+backend green; static assets cached; perf budget met.
4. **M3 — danielsmith.io**: static site via Sugarkube template; TLS green.
5. **M4 — jobbot3000**: split containers; smoke tests; host live.
6. **M5 — Hardening**: NetworkPolicies, backup configs, dashboard + alerts baseline saved.

---

## 8) Templates & Snippets

### 8.1) Example GitHub Action (multi‑arch build to GHCR)
```yaml
name: build-and-push
on: { push: { branches: ["main"] } }
jobs:
  docker:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-qemu-action@v3
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v6
        with:
          context: .
          platforms: linux/amd64,linux/arm64
          push: true
          tags: ghcr.io/<org>/<image>:${{ github.sha }},ghcr.io/<org>/<image>:edge
```

### 8.2) Kustomize overlay (app)
```yaml
# apps/token-place/overlays/prod/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: token-place
resources:
  - ../../base
images:
  - name: ghcr.io/futuroptimist/token-place-api
    newTag: vX.Y.Z
  - name: ghcr.io/futuroptimist/token-place-relay
    newTag: vX.Y.Z
configMapGenerator:
  - name: tp-config
    literals:
      LOG_LEVEL=info
```

### 8.3) Ingress (shared pattern)
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: web
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  ingressClassName: nginx
  tls:
    - hosts: [ "app.example.com" ]
      secretName: app-example-com-tls
  rules:
    - host: app.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: web
                port:
                  number: 80
```

---

## 9) Risks & Mitigations

- **ARM image gaps**: enforce multi‑arch builds early; add CI guard that fails on `amd64‑only` images.
- **Cert issuance**: use staging issuer while wiring DNS; switch to prod only after green path observed.
- **Ingress exposure**: choose one clear exposure path per env (MetalLB vs Tunnel) to avoid double‑routing surprises.
- **Persistent data**: start with `local-path` for low‑risk; migrate to Longhorn only when needed; back up before migrations.

---

## 10) Evergreen Maintenance

- Keep this blueprint in Git, versioned alongside the Flux overlays.
- Track app “orthogonality & saturation”: when `implement.md` yields overlapping diffs, pivot to `polish.md` tasks for structure, tests, and docs.
- Quarterly hygiene: upgrade controllers (Flux, cert-manager, ingress), rotate tokens, renew dashboards/alerts.

---

### References (for deeper reading)
- k3s quick start & storage (local‑path).
- Flux GitOps & Kustomize controller.
- Kubernetes Ingress model & NGINX Ingress Controller.
- cert‑manager (Let’s Encrypt, DNS‑01) and Cloudflare DNS challenge.
- Cloudflare Tunnel on Kubernetes (optional exposure path).
- ExternalDNS with Cloudflare (optional DNS automation).
- MetalLB (bare‑metal LoadBalancer).
- Longhorn (distributed block storage).
- kube‑prometheus‑stack (Prometheus Operator + Grafana).
- Docker Buildx for multi‑platform builds; GHCR publishing.
