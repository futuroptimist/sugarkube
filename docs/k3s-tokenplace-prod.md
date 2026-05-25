# k3s token.place runbook (prod)

Use this runbook for relay-only production deployments after staging sign-off.

## Topology and scope

- Release: `tokenplace`
- Namespace: `tokenplace`
- Chart: `oci://ghcr.io/futuroptimist/charts/tokenplace`
- Sugarkube runs only relay (`relay.py`) with single replica/worker, in-memory state.
- No in-cluster backend or GPU service.
- External compute remains out-of-cluster.

## Values and pins

- Base: `docs/examples/tokenplace.values.dev.yaml`
- Overlay: `docs/examples/tokenplace.values.prod.yaml`
- Version pin: `docs/apps/tokenplace.version`
- Approved prod tag pin: `docs/apps/tokenplace.prod.tag`

## Promote after staging sign-off

```bash
just tokenplace-oci-promote-prod tag=main-REPLACE_APPROVED_SHORTSHA
```

## Generic upgrade example (prod values)

```bash
just helm-oci-upgrade release=tokenplace namespace=tokenplace chart=oci://ghcr.io/futuroptimist/charts/tokenplace values=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.prod.yaml version_file=docs/apps/tokenplace.version default_tag=main-REPLACE_APPROVED_SHORTSHA
```

## Rollback options

1. Roll forward/rollback to prior immutable image tag using Helm OCI upgrade:

```bash
just helm-oci-upgrade release=tokenplace namespace=tokenplace chart=oci://ghcr.io/futuroptimist/charts/tokenplace values=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.prod.yaml version_file=docs/apps/tokenplace.version default_tag=main-REPLACE_PREVIOUS_SHORTSHA
```

2. Helm revision rollback:

```bash
helm -n tokenplace history tokenplace
just tokenplace-rollback release=tokenplace namespace=tokenplace revision=<known-good-revision>
```

## Validation

```bash
kubectl -n tokenplace get deploy,po,svc,ingress
kubectl -n tokenplace rollout status deploy/tokenplace --timeout=180s
curl -fsS https://token.place/livez
curl -fsS https://token.place/healthz
curl -fsS https://token.place/
```

## Troubleshooting

```bash
helm registry login ghcr.io
helm show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version "$(grep -E '^[0-9]+\.[0-9]+\.[0-9]+' docs/apps/tokenplace.version | head -n1)"
just tokenplace-status
just tokenplace-debug-logs-env env=prod
just cluster-status
just traefik-status
just cf-tunnel-debug
```

## Cloudflare Tunnel

Cloudflare routing is configured outside Helm. Ensure `token.place` routes to Traefik,
typically `http://traefik.kube-system.svc.cluster.local:80`.

```bash
just cf-tunnel-route host=token.place
```
