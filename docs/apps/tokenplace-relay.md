# token.place relay on Sugarkube

This runbook covers relay-only token.place operations on Sugarkube.

For the canonical app model, read [`docs/apps/tokenplace.md`](./tokenplace.md).
For onboarding context, read
[`docs/tokenplace_sugarkube_onboarding.md`](../tokenplace_sugarkube_onboarding.md).

## Scope

- Sugarkube runs only token.place `relay.py`.
- No in-cluster backend/GPU service is required.
- External compute nodes continue to run elsewhere (`server.py`, desktop Tauri app, Windows PCs,
  Apple Silicon Macs, Raspberry Pi compute nodes, etc.).
- Deployment is intentionally single-replica, single-worker, and in-memory.
- State loss on pod restart/eviction is currently accepted.

## Canonical deployment identifiers

- Image: `ghcr.io/futuroptimist/tokenplace-relay`
- Chart: `oci://ghcr.io/futuroptimist/charts/tokenplace`
- Release: `tokenplace`
- Namespace: `tokenplace`
- Version pin: `docs/apps/tokenplace.version`
- Prod tag pin: `docs/apps/tokenplace.prod.tag`

## Values layering

- Base: `docs/examples/tokenplace.values.dev.yaml`
- Staging overlay: `docs/examples/tokenplace.values.staging.yaml`
- Prod overlay: `docs/examples/tokenplace.values.prod.yaml`

Do not prefer `./apps/tokenplace-relay` for steady-state deployments.

## Cloudflare + Traefik model

- Staging host default: `staging.token.place`
- Production host default: `token.place`
- Cloudflare routes are managed outside Helm and should target Traefik:
  `http://traefik.kube-system.svc.cluster.local:80`
- Helper examples:
  - `just cf-tunnel-route host=staging.token.place`
  - `just cf-tunnel-route host=token.place`

## Common operational commands

- Deploy staging: `just tokenplace-oci-deploy env=staging tag=main-REPLACE_SHORTSHA`
- Promote prod: `just tokenplace-oci-promote-prod tag=main-REPLACE_APPROVED_SHORTSHA`
- Status: `just tokenplace-status`
- Debug logs:
  - `just tokenplace-debug-logs-env env=staging`
  - `just tokenplace-debug-logs-env env=prod`
