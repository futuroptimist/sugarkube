# token.place on Sugarkube

This is the canonical operations guide for token.place on Sugarkube.

For onboarding context and environment ownership boundaries, start with
[`docs/tokenplace_sugarkube_onboarding.md`](../tokenplace_sugarkube_onboarding.md).

## Current production scope (relay-only)

Sugarkube currently runs **only** `token.place` `relay.py`.

- **In-cluster (Sugarkube):** one relay deployment (`tokenplace`) behind Traefik ingress.
- **Not in-cluster:** no backend service and no GPU service are deployed on Sugarkube.
- **External compute nodes:** remain outside the cluster (for example `server.py`, desktop Tauri app,
  Windows PCs, Apple Silicon Macs, Raspberry Pi compute nodes).
- **Runtime model today:** single replica, single worker, in-memory relay state.
- **Failure model:** state loss on pod death is accepted for now.
- **Out of scope:** multi-replica relay coordination and in-memory database architecture.

## Artifact and release model

- Image: `ghcr.io/futuroptimist/tokenplace-relay`
- Chart: `oci://ghcr.io/futuroptimist/charts/tokenplace`
- Release: `tokenplace`
- Namespace: `tokenplace`
- Version pin: `docs/apps/tokenplace.version`
- Production approved tag pin: `docs/apps/tokenplace.prod.tag`

## Values model

Layer values exactly like DSPACE-style OCI deploys:

- Base: `docs/examples/tokenplace.values.dev.yaml`
- Staging overlay: `docs/examples/tokenplace.values.staging.yaml`
- Production overlay: `docs/examples/tokenplace.values.prod.yaml`

Default hosts:

- Staging: `staging.token.place`
- Production: `token.place`

## Deployment entrypoints

Primary environment-aware wrappers:

- `just tokenplace-oci-deploy env=staging tag=<immutable-tag>`
- `just tokenplace-oci-deploy env=prod tag=<immutable-tag>`
- `just tokenplace-oci-promote-prod tag=<approved-immutable-tag>`

Generic OCI helper commands are still available as secondary references:

- `just helm-oci-install ...`
- `just helm-oci-upgrade ...`

## Cloudflare + ingress model

Cloudflare tunnel routing is managed **outside** Helm charts.

- Route `staging.token.place` and `token.place` to Traefik, typically:
  `http://traefik.kube-system.svc.cluster.local:80`
- Helm deploys Kubernetes resources only; it does **not** create Cloudflare routes.
- If available in your operator workflow, use:
  - `just cf-tunnel-route host=staging.token.place`
  - `just cf-tunnel-route host=token.place`

## Day-2 validation and troubleshooting shortcuts

- App status: `just tokenplace-status`
- Logs by environment:
  - `just tokenplace-debug-logs-env env=staging`
  - `just tokenplace-debug-logs-env env=prod`
- Cluster edge path checks:
  - `just cluster-status`
  - `just traefik-status`
  - `just cf-tunnel-debug`

For concrete per-environment procedures, use:

- [`docs/k3s-tokenplace-staging.md`](../k3s-tokenplace-staging.md)
- [`docs/k3s-tokenplace-prod.md`](../k3s-tokenplace-prod.md)
