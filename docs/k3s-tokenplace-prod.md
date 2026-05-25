# k3s token.place runbook (prod)

Use this runbook for `prod` relay-only token.place deployments on Sugarkube.

## Scope

- In-cluster workload: `relay.py` only.
- No in-cluster backend/GPU service.
- External compute remains out-of-cluster.

## Canonical identifiers

- Release: `tokenplace`
- Namespace: `tokenplace`
- Chart: `oci://ghcr.io/futuroptimist/charts/tokenplace`
- Version pin: `docs/apps/tokenplace.version`
- Prod tag pin: `docs/apps/tokenplace.prod.tag`
- Values: `docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.prod.yaml`
- Prod host: `token.place`

## Promotion after staging sign-off

```bash
just tokenplace-oci-promote-prod tag=main-REPLACE_APPROVED_SHORTSHA
```

## Generic production upgrade

```bash
just helm-oci-upgrade release=tokenplace namespace=tokenplace chart=oci://ghcr.io/futuroptimist/charts/tokenplace values=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.prod.yaml version_file=docs/apps/tokenplace.version default_tag=main-REPLACE_APPROVED_SHORTSHA
```

## Rollback options

### Roll back by immutable image tag

```bash
just helm-oci-upgrade release=tokenplace namespace=tokenplace chart=oci://ghcr.io/futuroptimist/charts/tokenplace values=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.prod.yaml version_file=docs/apps/tokenplace.version default_tag=main-REPLACE_PREVIOUS_SHORTSHA
```

### Roll back by Helm revision

```bash
just tokenplace-rollback
```

## Validation

```bash
kubectl -n tokenplace get deploy,po,svc,ingress
kubectl -n tokenplace rollout status deploy/tokenplace --timeout=180s
curl -fsS https://token.place/livez
curl -fsS https://token.place/healthz
curl -fsS https://token.place/
```

## Cloudflare Tunnel expectations

- Cloudflare route/tunnel configuration is outside Helm.
- Route `token.place` to Traefik, typically
  `http://traefik.kube-system.svc.cluster.local:80`.
- If available, use:

```bash
just cf-tunnel-route host=token.place
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
