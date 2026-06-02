# token.place Sugarkube onboarding

This guide defines the concrete Sugarkube operating contract for token.place relay deployments.

## Scope and topology

Current scope is **relay-only** on Sugarkube:

- Sugarkube runs only `relay.py`.
- No in-cluster backend/GPU service is required.
- Compute nodes remain external (`server.py`, desktop Tauri app, Windows PCs, Apple Silicon Macs,
  Raspberry Pi compute nodes, and other remote workers).
- Runtime defaults are one replica, one Gunicorn worker, and in-memory state; validate the rendered Kubernetes Deployment contract for `spec.strategy.type: Recreate` before rollout.
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

Do not carry forward one-off Helm `--set env.XDG_*=/tmp` overrides from the initial staging incident response. XDG `/tmp` behavior is now expected from chart defaults, and Sugarkube overlays should only carry environment-specific values.

## Promotion gate ownership

Staging-to-prod promotion is blocked until the real relay-compute path passes. Web/TLS readiness,
`/livez`, `/healthz`, `/`, `/metrics`, and synthetic register/poll checks do not replace desktop
compute-node registration plus an E2EE request/response. Keep release evidence with chart digest,
image tag, deployment YAML, health/diagnostics responses, and relay logs from after the compute test.

## Environment runbooks

- App overview: `docs/apps/tokenplace.md`
- Relay runbook: `docs/apps/tokenplace-relay.md`
- Staging runbook: `docs/k3s-tokenplace-staging.md`
- Production runbook: `docs/k3s-tokenplace-prod.md`


## 0.1.0 release alignment

- Chart version: `0.1.0`
- Chart `appVersion`: `0.1.0`
- token.place Git tag: `v0.1.0`
- Release image tag: `ghcr.io/futuroptimist/tokenplace-relay:v0.1.0`
- Staging candidate image tag: `main-REPLACE_SHORTSHA`

## Cloudflare model

Cloudflare tunnels/routes are managed outside Helm, and Helm does not manage Cloudflare hostname routing. Use route mappings from hostname to Traefik
(typically `http://traefik.kube-system.svc.cluster.local:80`) before deploy/upgrade steps.
