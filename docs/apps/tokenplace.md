# token.place on Sugarkube

This is the canonical Sugarkube deployment model for token.place.

For onboarding ownership and environment sequencing, see
[`docs/tokenplace_sugarkube_onboarding.md`](../tokenplace_sugarkube_onboarding.md).

## Relay-only topology (current scope)

Sugarkube currently runs **only** the token.place relay service (`relay.py`).

- **In-cluster (Sugarkube):** one relay deployment exposed through Traefik ingress.
- **Out-of-cluster compute:** `server.py`, desktop Tauri app, Windows PCs, Apple Silicon Macs,
  Raspberry Pi compute nodes, and other compute workers remain external.
- **No in-cluster backend/GPU service** is required for steady-state relay operation.
- **Single replica + single worker** defaults are intentional.
- Relay state is currently **in-memory only**; pod restarts lose relay memory/state and this is
  accepted for now.
- Future in-memory database or multi-replica architecture is **out of scope** for this runbook.

## Artifact model (canonical)

- Image: `ghcr.io/futuroptimist/tokenplace-relay`
- Chart: `oci://ghcr.io/futuroptimist/charts/tokenplace`
- Helm release: `tokenplace`
- Namespace: `tokenplace`
- Chart version pin file: `docs/apps/tokenplace.version`
- Production approved tag pin: `docs/apps/tokenplace.prod.tag`

## Values model

- Base: `docs/examples/tokenplace.values.dev.yaml`
- Staging overlay: `docs/examples/tokenplace.values.staging.yaml`
- Production overlay: `docs/examples/tokenplace.values.prod.yaml`

Chart-owned runtime env defaults (worker count, frontend mode, relay upstream-health gating, and XDG `/tmp` paths) should remain in the token.place chart. Keep Sugarkube values focused on environment-specific keys like `TOKEN_PLACE_ENV`, `TOKENPLACE_RELAY_PUBLIC_URL`, ingress hosts, and TLS secrets.

Default hosts:

- Staging: `staging.token.place`
- Production: `token.place`

## Core deployment commands

Use concrete release/namespace/chart values for token.place relay deployments.

```bash
just kubeconfig-env staging
TOKENPLACE_TAG=main-deadbee # replace with the immutable tag you want to deploy
just helm-oci-install release=tokenplace namespace=tokenplace chart=oci://ghcr.io/futuroptimist/charts/tokenplace values=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.staging.yaml version_file=docs/apps/tokenplace.version default_tag="$TOKENPLACE_TAG"
```

```bash
just kubeconfig-env staging
TOKENPLACE_TAG=main-deadbee # replace with the immutable tag you want to deploy
just helm-oci-upgrade release=tokenplace namespace=tokenplace chart=oci://ghcr.io/futuroptimist/charts/tokenplace values=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.staging.yaml version_file=docs/apps/tokenplace.version default_tag="$TOKENPLACE_TAG"
```

Preferred env wrapper:

```bash
TOKENPLACE_TAG=main-deadbee # replace with the immutable tag you want to deploy
just tokenplace-oci-deploy env=staging tag="$TOKENPLACE_TAG"
```

## Validation commands

```bash
kubectl -n tokenplace get deploy,po,svc,ingress
kubectl -n tokenplace rollout status deploy/tokenplace --timeout=180s
curl -fsS https://staging.token.place/livez
curl -fsS https://staging.token.place/healthz
curl -fsS https://staging.token.place/relay/diagnostics
curl -fsS https://staging.token.place/
```

For production validation, use the same checks against `https://token.place`. Avoid long-running
public `/healthz` watches as readiness monitors until health, liveness, metrics, diagnostics, and
API v1 compute-node heartbeat routes are confirmed exempt from public API rate limits; prefer
`kubectl -n tokenplace get endpoints`, `kubectl -n tokenplace get deploy,po`, relay logs, and
low-frequency diagnostics curls for operational readiness. Staging/prod signoff also requires
synthetic API v1 register/poll, an external desktop or compute-node registration, and an E2EE
request/response through the relay; see the staging runbook for the full sequence and curl payloads.

## Cloudflare and ingress model

Cloudflare Tunnel/DNS configuration is external to Helm.

- Route hostnames to Traefik, typically
  `http://traefik.kube-system.svc.cluster.local:80`.
- Helm chart deployment does **not** create Cloudflare routes.
- One tunnel per environment can serve multiple app hostnames (for example
  `staging.democratized.space` and `staging.token.place`) by routing both to Traefik.
- Traefik chooses the correct Kubernetes Ingress by HTTP `Host` header.
- Staging/prod overlays set `ingress.tls.enabled: true` so rendered Kubernetes Ingress includes `spec.tls`.
- `cert-manager` and a compatible `ClusterIssuer` are assumed to already exist.
- Cloudflare Tunnel routing (`cf-tunnel-route`) is separate from the Cloudflare DNS API token used
  by cert-manager DNS-01.
- Configure routes explicitly:

```bash
just cf-tunnel-route staging.token.place
just cf-tunnel-route host=staging.token.place
just cf-tunnel-route token.place
just cf-tunnel-route host=token.place
```

## Related runbooks

- Relay-focused app guide: [`docs/apps/tokenplace-relay.md`](./tokenplace-relay.md)
- Staging runbook: [`docs/k3s-tokenplace-staging.md`](../k3s-tokenplace-staging.md)
- Production runbook: [`docs/k3s-tokenplace-prod.md`](../k3s-tokenplace-prod.md)


## 0.1.0 release alignment

- Chart version: `0.1.0`
- Chart `appVersion`: `0.1.0`
- Git tag: `v0.1.0`
- Release image tag: `v0.1.0` (`ghcr.io/futuroptimist/tokenplace-relay:v0.1.0`)
- Staging candidate image tag: `main-<shortsha>`
