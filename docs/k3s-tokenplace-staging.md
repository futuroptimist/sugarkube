# k3s token.place runbook (staging)

Use this runbook for `staging` relay-only token.place deployments on Sugarkube.

## Scope

- In-cluster workload: `relay.py` only.
- No in-cluster backend/GPU service.
- External compute remains out-of-cluster.

## Canonical identifiers

- Release: `tokenplace`
- Namespace: `tokenplace`
- Chart: `oci://ghcr.io/futuroptimist/charts/tokenplace`
- Version pin: `docs/apps/tokenplace.version`
- Values: `docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.staging.yaml`
- Staging host: `staging.token.place`

## First install

```bash
just helm-oci-install release=tokenplace namespace=tokenplace chart=oci://ghcr.io/futuroptimist/charts/tokenplace values=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.staging.yaml version_file=docs/apps/tokenplace.version default_tag=main-REPLACE_SHORTSHA
```

## Existing release upgrade

```bash
just helm-oci-upgrade release=tokenplace namespace=tokenplace chart=oci://ghcr.io/futuroptimist/charts/tokenplace values=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.staging.yaml version_file=docs/apps/tokenplace.version default_tag=main-REPLACE_SHORTSHA
```

## Preferred wrapper

```bash
just tokenplace-oci-deploy env=staging tag=main-REPLACE_SHORTSHA
```

## Validation

```bash
kubectl -n tokenplace get deploy,po,svc,ingress
kubectl -n tokenplace rollout status deploy/tokenplace --timeout=180s
curl -fsS https://staging.token.place/livez
curl -fsS https://staging.token.place/healthz
curl -fsS https://staging.token.place/
```

## Cloudflare Tunnel expectations

- Cloudflare route/tunnel configuration is outside Helm.
- Route `staging.token.place` to Traefik, typically
  `http://traefik.kube-system.svc.cluster.local:80`.
- If available, use:

```bash
just cf-tunnel-route host=staging.token.place
```

## Troubleshooting

```bash
helm registry login ghcr.io
helm show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version "$(grep -E '^[0-9]+\.[0-9]+\.[0-9]+' docs/apps/tokenplace.version | head -n1)"
just tokenplace-status
just tokenplace-debug-logs-env env=staging
just cluster-status
just traefik-status
just cf-tunnel-debug
```
