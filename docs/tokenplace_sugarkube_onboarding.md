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

## Environment runbooks

- App overview: `docs/apps/tokenplace.md`
- Relay runbook: `docs/apps/tokenplace-relay.md`
- Staging runbook: `docs/k3s-tokenplace-staging.md`
- Production runbook: `docs/k3s-tokenplace-prod.md`

## Cloudflare model

Cloudflare tunnels/routes are managed outside Helm. Use route mappings from hostname to Traefik
(typically `http://traefik.kube-system.svc.cluster.local:80`) before deploy/upgrade steps.

## 0.1.0 release alignment

- Chart package version: `0.1.0`
- Chart `appVersion`: `0.1.0`
- token.place Git tag: `v0.1.0`
- Release image tag: `v0.1.0` (`ghcr.io/futuroptimist/tokenplace-relay:v0.1.0`)
- Staging candidate image tag before final promotion: `main-<shortsha>`

