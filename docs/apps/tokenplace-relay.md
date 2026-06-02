# token.place relay on Sugarkube

This guide documents the **relay-only** token.place deployment on Sugarkube.

- Sugarkube runs only `relay.py`.
- No in-cluster backend/GPU service is required.
- Compute nodes remain external (`server.py`, Tauri desktop app, Windows/Apple Silicon/Raspberry Pi nodes, etc.).
- Runtime is intentionally one replica, one Gunicorn worker, and in-memory state; verify the rendered Kubernetes Deployment contract includes `spec.strategy.type: Recreate` before rollout.
- In-memory state loss on pod restart is accepted at this stage.

For the broader app overview, see [`docs/apps/tokenplace.md`](./tokenplace.md).

## Canonical artifacts and release IDs

- Image: `ghcr.io/futuroptimist/tokenplace-relay`
- Chart: `oci://ghcr.io/futuroptimist/charts/tokenplace`
- Release: `tokenplace`
- Namespace: `tokenplace`
- Version pin: `docs/apps/tokenplace.version`
- Prod approved tag pin: `docs/apps/tokenplace.prod.tag`

## Values files

- Base values: `docs/examples/tokenplace.values.dev.yaml`
- Staging overlay: `docs/examples/tokenplace.values.staging.yaml`
- Prod overlay: `docs/examples/tokenplace.values.prod.yaml`

Defaults:

- Staging host: `staging.token.place`
- Production host: `token.place`

## Staging install/upgrade

Preferred generic deploy:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just app-deploy app=tokenplace env=staging tag="$APP_TAG"
```

Compatibility wrapper:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just tokenplace-oci-deploy env=staging tag="$APP_TAG"
```

## Staging validation

```bash
kubectl -n tokenplace get deploy,po,svc,ingress
kubectl -n tokenplace rollout status deploy/tokenplace --timeout=180s
curl -fsS https://staging.token.place/livez
curl -fsS https://staging.token.place/healthz
curl -fsS https://staging.token.place/
```

## Production promotion, deploy, and rollback

Promote only the immutable staging image tag that passed relay validation. Final
production promotion after a token.place Git tag push may use `v0.1.0` or the
current approved release tag.

Preferred generic production promotion:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just app-promote-prod app=tokenplace tag="$APP_TAG"
```

Compatibility wrapper:

```bash
just tokenplace-oci-promote-prod tag="$APP_TAG"
```

Rollback using previous immutable tag:

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA
```

```bash
just app-promote-prod app=tokenplace tag="$APP_TAG"
```

Rollback to previous Helm revision:

```bash
APP_REVISION=12
```

```bash
just tokenplace-rollback release=tokenplace namespace=tokenplace revision="$APP_REVISION"
```

Production validation:

```bash
kubectl -n tokenplace get deploy,po,svc,ingress
kubectl -n tokenplace rollout status deploy/tokenplace --timeout=180s
curl -fsS https://token.place/livez
curl -fsS https://token.place/healthz
curl -fsS https://token.place/
```

## Cloudflare tunnel guidance

Use the same DSPACE-style tunnel model:

- Cloudflare hostname routes point to Traefik, typically
  `http://traefik.kube-system.svc.cluster.local:80`.
- Staging/prod tunnel and DNS routes are configured outside Helm.
- The chart deploy does not create Cloudflare routes.
- Staging/prod overlays set `ingress.tls.enabled: true` so rendered Kubernetes Ingress includes `spec.tls` (with `tokenplace-staging-tls` and `tokenplace-prod-tls`).
- `cert-manager` and the referenced `ClusterIssuer` are assumed to already exist.

Helpful commands:

```bash
just cf-tunnel-route host=staging.token.place
just cf-tunnel-route host=token.place
```

## Troubleshooting

GHCR auth and chart visibility:

```bash
echo "$GHCR_TOKEN" | helm registry login ghcr.io -u "$GHCR_USER" --password-stdin
helm show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version "$(grep -E '^[0-9]+\.[0-9]+\.[0-9]+' docs/apps/tokenplace.version | head -n1)"
```

App and logs:

```bash
just tokenplace-status
just tokenplace-debug-logs-env env=staging
just tokenplace-debug-logs-env env=prod
```

Ingress/Traefik/Tunnel:

```bash
just cluster-status
just traefik-status
just cf-tunnel-debug
```


## 0.1.0 release alignment

- Chart version: `0.1.0`
- Chart `appVersion`: `0.1.0`
- Git tag: `v0.1.0`
- Release image tag: `v0.1.0`
- Staging candidate image tag: `main-REPLACE_SHORTSHA`
