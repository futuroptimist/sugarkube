# token.place on Sugarkube

This guide defines the canonical relay-only token.place deployment on Sugarkube.

For onboarding and environment runbooks, see
[`docs/tokenplace_sugarkube_onboarding.md`](../tokenplace_sugarkube_onboarding.md),
[`docs/k3s-tokenplace-staging.md`](../k3s-tokenplace-staging.md), and
[`docs/k3s-tokenplace-prod.md`](../k3s-tokenplace-prod.md).

## Relay-only topology (current scope)

Sugarkube currently runs only `token.place` `relay.py`.

- **In-cluster (Sugarkube):** one relay deployment, one replica, one worker, in-memory state.
- **Not in-cluster:** no backend service and no GPU service are deployed on Sugarkube.
- **External compute remains external:** `server.py`, the desktop Tauri app, Windows PCs,
  Apple Silicon Macs, Raspberry Pi compute nodes, and other compute workers run outside the
  Sugarkube cluster.

Operational constraints for this phase:

- Pod state loss on restart/eviction is accepted.
- Multi-replica state sharing and an in-memory DB layer are explicitly out of scope for now.

## Canonical artifacts and release identity

- Image: `ghcr.io/futuroptimist/tokenplace-relay`
- Chart: `oci://ghcr.io/futuroptimist/charts/tokenplace`
- Release: `tokenplace`
- Namespace: `tokenplace`
- Chart version pin: `docs/apps/tokenplace.version`
- Production approved image tag pin: `docs/apps/tokenplace.prod.tag`

## Values model

Use DSPACE-style layered values:

- Base: `docs/examples/tokenplace.values.dev.yaml`
- Staging overlay: `docs/examples/tokenplace.values.staging.yaml`
- Prod overlay: `docs/examples/tokenplace.values.prod.yaml`

Host defaults:

- Staging: `staging.token.place`
- Prod: `token.place`

## Cloudflare + ingress model

Cloudflare routing is configured outside Helm.

- Helm deploys Kubernetes resources only.
- Cloudflare Tunnel/DNS must route public hosts to Traefik, typically:
  `http://traefik.kube-system.svc.cluster.local:80`
- Use existing helper guidance where available:
  - `just cf-tunnel-route host=staging.token.place`
  - `just cf-tunnel-route host=token.place`

See also [`docs/cloudflare_tunnel.md`](../cloudflare_tunnel.md).

## Primary operator flow

- Staging deploy and validation: [`docs/k3s-tokenplace-staging.md`](../k3s-tokenplace-staging.md)
- Production promotion/deploy/rollback: [`docs/k3s-tokenplace-prod.md`](../k3s-tokenplace-prod.md)
- Relay app specifics and troubleshooting: [`docs/apps/tokenplace-relay.md`](./tokenplace-relay.md)
