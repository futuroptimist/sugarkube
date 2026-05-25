# token.place Sugarkube onboarding

This onboarding guide defines the relay-only operating contract for token.place on Sugarkube.

## Deployment contract

Sugarkube token.place deployments currently use the following fixed model:

- Runtime scope: relay-only (`relay.py`) on Sugarkube.
- In-cluster services: no required backend/GPU service.
- External compute scope: `server.py`, desktop Tauri app, Windows PCs, Apple Silicon Macs,
  Raspberry Pi compute nodes, and other external workers.
- Current HA/state model: one relay replica, one worker, in-memory state.
- Accepted behavior: state may be lost on pod death/recreation.
- Out of scope for this phase: multi-replica relay and in-memory database architecture.

## Canonical artifacts and pins

- Image: `ghcr.io/futuroptimist/tokenplace-relay`
- Chart: `oci://ghcr.io/futuroptimist/charts/tokenplace`
- Release: `tokenplace`
- Namespace: `tokenplace`
- Chart version pin file: `docs/apps/tokenplace.version`
- Production-approved image tag file: `docs/apps/tokenplace.prod.tag`

## Values contract

Use environment overlays on top of shared defaults:

- Base: `docs/examples/tokenplace.values.dev.yaml`
- Staging: `docs/examples/tokenplace.values.staging.yaml`
- Production: `docs/examples/tokenplace.values.prod.yaml`

## Cloudflare contract

Cloudflare Tunnel + DNS routing is managed outside Helm.

- Hostnames are routed to Traefik (typically
  `http://traefik.kube-system.svc.cluster.local:80`).
- Helm chart deployment does not create Cloudflare routes.
- Suggested helpers:
  - `just cf-tunnel-route host=staging.token.place`
  - `just cf-tunnel-route host=token.place`

## Where to run operations

- App guide: `docs/apps/tokenplace.md`
- Relay guide: `docs/apps/tokenplace-relay.md`
- Staging runbook: `docs/k3s-tokenplace-staging.md`
- Production runbook: `docs/k3s-tokenplace-prod.md`
