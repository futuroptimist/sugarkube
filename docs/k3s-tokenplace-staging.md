# k3s token.place runbook (staging)

Use this runbook for relay-only staging deployments.

## Topology and scope

- Release: `tokenplace`
- Namespace: `tokenplace`
- Chart: `oci://ghcr.io/futuroptimist/charts/tokenplace`
- Sugarkube runs only relay (`relay.py`), single replica/worker, in-memory state.
- No in-cluster backend/GPU service is required.
- External compute remains outside the cluster.

## Values files

- Base: `docs/examples/tokenplace.values.dev.yaml`
- Overlay: `docs/examples/tokenplace.values.staging.yaml`
- Version pin: `docs/apps/tokenplace.version`

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

## Cloudflare Tunnel

Cloudflare routing is managed outside Helm. Ensure `staging.token.place` points to Traefik,
typically `http://traefik.kube-system.svc.cluster.local:80`.

```bash
just cf-tunnel-route host=staging.token.place
```
