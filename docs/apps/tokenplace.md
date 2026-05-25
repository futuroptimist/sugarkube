# token.place on Sugarkube

This is the canonical Sugarkube operations guide for token.place relay-only deployments.

For onboarding + environment runbooks, start with
[`docs/tokenplace_sugarkube_onboarding.md`](../tokenplace_sugarkube_onboarding.md).

## Current supported topology (relay-only)

Sugarkube currently runs only `relay.py` for token.place.

- **In-cluster (Sugarkube):** one relay deployment behind Traefik ingress.
- **Out-of-cluster compute:** `server.py`, desktop Tauri app, Windows PCs, Apple Silicon Macs,
  Raspberry Pi compute nodes, and other compute workers.
- **No in-cluster backend/GPU service:** this is intentional for the current rollout.
- **Single replica / single worker / in-memory state:** accepted for now.
- **Pod death can drop relay state:** accepted for now.
- **Out of scope for this phase:** multi-replica relay and in-memory database architectures.

## Canonical artifact model

Use these fixed identifiers for staging and production operations:

- Image: `ghcr.io/futuroptimist/tokenplace-relay`
- Chart: `oci://ghcr.io/futuroptimist/charts/tokenplace`
- Release: `tokenplace`
- Namespace: `tokenplace`
- Chart version pin: `docs/apps/tokenplace.version`
- Production-approved image tag pin: `docs/apps/tokenplace.prod.tag`

## Values model

Layer values in this order:

1. Base shared defaults: `docs/examples/tokenplace.values.dev.yaml`
2. Staging overlay: `docs/examples/tokenplace.values.staging.yaml`
3. Production overlay: `docs/examples/tokenplace.values.prod.yaml`

Default ingress hosts:

- Staging: `staging.token.place`
- Production: `token.place`

## Deployment workflow (OCI chart/image)

Preferred deployment wrappers:

- Staging deploy: `just tokenplace-oci-deploy env=staging tag=<immutable-tag>`
- Production promote/deploy: `just tokenplace-oci-promote-prod tag=<immutable-tag>`
- Debug logs by env:
  - `just tokenplace-debug-logs-env env=staging`
  - `just tokenplace-debug-logs-env env=prod`

Generic Helm OCI helpers are still available as secondary references, but token.place operations
should default to the tokenplace-specific wrappers above.

## Cloudflare + ingress model

Cloudflare Tunnel routes are configured **outside Helm**.

- Cloudflare routes should point app hostnames to Traefik, typically:
  `http://traefik.kube-system.svc.cluster.local:80`
- Helm deploys Kubernetes resources only; it does not create Cloudflare routes.
- Common helper commands:
  - `just cf-tunnel-route host=staging.token.place`
  - `just cf-tunnel-route host=token.place`

## Validation and troubleshooting quick reference

- App status: `just tokenplace-status`
- Cluster/ingress status:
  - `just cluster-status`
  - `just traefik-status`
  - `just cf-tunnel-debug`
- GHCR auth / chart verify:
  - `helm registry login ghcr.io`
  - `helm show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version "$(grep -E '^[0-9]+\.[0-9]+\.[0-9]+' docs/apps/tokenplace.version | head -n1)"`

For step-by-step commands, use:

- [`docs/k3s-tokenplace-staging.md`](../k3s-tokenplace-staging.md)
- [`docs/k3s-tokenplace-prod.md`](../k3s-tokenplace-prod.md)
