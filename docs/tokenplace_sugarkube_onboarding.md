# token.place Sugarkube onboarding

This onboarding guide is now aligned to the relay-only Sugarkube deployment model.

## Deployment scope now

Sugarkube runs only `token.place` `relay.py` as the in-cluster workload.

- No in-cluster backend/GPU service is required.
- External compute nodes remain external (`server.py`, desktop Tauri app, Windows PCs,
  Apple Silicon Macs, Raspberry Pi compute nodes, etc.).
- Relay runtime for Sugarkube is a single replica with one worker and in-memory state.
- Pod restart state loss is currently accepted.
- Multi-replica stateful architecture is intentionally out of scope.

## Canonical release model

- Image: `ghcr.io/futuroptimist/tokenplace-relay`
- Chart: `oci://ghcr.io/futuroptimist/charts/tokenplace`
- Release: `tokenplace`
- Namespace: `tokenplace`
- Version pin: `docs/apps/tokenplace.version`
- Prod tag pin: `docs/apps/tokenplace.prod.tag`

## Values model

- Base: `docs/examples/tokenplace.values.dev.yaml`
- Staging overlay: `docs/examples/tokenplace.values.staging.yaml`
- Prod overlay: `docs/examples/tokenplace.values.prod.yaml`

## Runbooks

- Staging: `docs/k3s-tokenplace-staging.md`
- Production: `docs/k3s-tokenplace-prod.md`
- Relay app details: `docs/apps/tokenplace-relay.md`
- App overview: `docs/apps/tokenplace.md`

## Cloudflare boundary

Cloudflare tunnels/routes are not managed by the Helm chart.

- Route staging/prod hosts to Traefik (typically
  `http://traefik.kube-system.svc.cluster.local:80`).
- Use helpers where available:
  - `just cf-tunnel-route host=staging.token.place`
  - `just cf-tunnel-route host=token.place`
