# token.place Sugarkube onboarding

This guide defines the concrete Sugarkube operating contract for token.place relay deployments.

## Scope and topology

Current scope is **relay-only** on Sugarkube:

- Sugarkube runs only `relay.py`.
- No in-cluster backend/GPU service is required.
- Compute nodes remain external (`server.py`, desktop Tauri app, Windows PCs, Apple Silicon Macs,
  Raspberry Pi compute nodes, and other remote workers).
- Runtime defaults are one replica and one worker with in-memory state.
- State loss on pod restart is currently accepted.
- Future multi-replica / in-memory database architecture is out of scope for this runbook.

## Canonical artifacts and IDs

- Image: `ghcr.io/futuroptimist/tokenplace-relay`
- Chart: `oci://ghcr.io/futuroptimist/charts/tokenplace`
- Release: `tokenplace`
- Namespace: `tokenplace`
- Version pin file: `docs/apps/tokenplace.version`
- Production approved tag file: `docs/apps/tokenplace.prod.tag`

## Values model

- Base defaults: `docs/examples/tokenplace.values.dev.yaml`
- Staging overlay: `docs/examples/tokenplace.values.staging.yaml`
- Production overlay: `docs/examples/tokenplace.values.prod.yaml`

Host defaults:

- Staging: `staging.token.place`
- Production: `token.place`

## 0.1.0 release alignment

- Helm chart package version: `0.1.0`
- Helm chart `appVersion`: `0.1.0`
- token.place Git tag: `v0.1.0`
- Release image tag after tag push: `ghcr.io/futuroptimist/tokenplace-relay:v0.1.0`
- Staging candidate tag before final tagging: `main-<shortsha>`

## Environment runbooks

- App overview: `docs/apps/tokenplace.md`
- Relay runbook: `docs/apps/tokenplace-relay.md`
- Staging runbook: `docs/k3s-tokenplace-staging.md`
- Production runbook: `docs/k3s-tokenplace-prod.md`

## Cloudflare model

Cloudflare Tunnel/DNS routes are managed outside Helm. Helm deploy/upgrade does not configure Cloudflare hostnames; map each hostname to Traefik (typically `http://traefik.kube-system.svc.cluster.local:80`) before deploy/upgrade steps. Staging/prod overlays now explicitly enable `ingress.tls.enabled: true` so Kubernetes Ingress `spec.tls` renders correctly with cert-manager and an existing ClusterIssuer.
