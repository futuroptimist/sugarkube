# k3s token.place runbook (prod)

Use this runbook for relay-only token.place production deployments on Sugarkube.

## Topology and scope

- Sugarkube runs only token.place relay (`relay.py`).
- No in-cluster backend/GPU service is required.
- Compute nodes remain external (`server.py`, Tauri desktop app, Windows PCs, Apple Silicon Macs,
  Raspberry Pi compute nodes, etc.).
- Runtime model is single replica + single worker + in-memory state.
- In-memory state loss on pod restart is accepted for now.

## Artifact and values contract

- Chart: `oci://ghcr.io/futuroptimist/charts/tokenplace`
- Image: `ghcr.io/futuroptimist/tokenplace-relay`
- Release: `tokenplace`
- Namespace: `tokenplace`
- Version pin file: `docs/apps/tokenplace.version`
- Approved prod tag file: `docs/apps/tokenplace.prod.tag`
- Values: `docs/examples/tokenplace.values.dev.yaml` + `docs/examples/tokenplace.values.prod.yaml`
- Default production host: `token.place`

## Promotion after staging sign-off

```bash
TOKENPLACE_TAG=main-deadbee # replace with the approved immutable tag
just tokenplace-oci-promote-prod tag="$TOKENPLACE_TAG"
```

## Generic production upgrade

Select the production kube context first (or use the wrapper above):

```bash
just kubeconfig-env prod
```

Then run the generic OCI helper:

```bash
TOKENPLACE_TAG=main-deadbee # replace with the approved immutable tag
just helm-oci-upgrade release=tokenplace namespace=tokenplace chart=oci://ghcr.io/futuroptimist/charts/tokenplace values=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.prod.yaml version_file=docs/apps/tokenplace.version default_tag="$TOKENPLACE_TAG"
```

## Validation

```bash
kubectl -n tokenplace get deploy,po,svc,ingress
kubectl -n tokenplace rollout status deploy/tokenplace --timeout=180s
curl -fsS https://token.place/livez
curl -fsS https://token.place/healthz
curl -fsS https://token.place/
```

## Rollback options

Rollback by immutable tag:

```bash
TOKENPLACE_PREVIOUS_TAG=main-deadbee # replace with the prior immutable tag
just helm-oci-upgrade release=tokenplace namespace=tokenplace chart=oci://ghcr.io/futuroptimist/charts/tokenplace values=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.prod.yaml version_file=docs/apps/tokenplace.version default_tag="$TOKENPLACE_PREVIOUS_TAG"
```

Rollback by Helm revision:

```bash
TOKENPLACE_REVISION=12 # replace with the known-good Helm revision
just tokenplace-rollback release=tokenplace namespace=tokenplace revision="$TOKENPLACE_REVISION"
```

## Cloudflare tunnel routing (external to Helm)

Cloudflare routes are configured outside the chart. Route `token.place` to Traefik,
typically `http://traefik.kube-system.svc.cluster.local:80`.

```bash
just cf-tunnel-route host=token.place
```

## Troubleshooting

GHCR auth/chart checks:

```bash
echo "$GHCR_TOKEN" | helm registry login ghcr.io -u "$GHCR_USER" --password-stdin
helm show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version "$(grep -E '^[0-9]+\.[0-9]+\.[0-9]+' docs/apps/tokenplace.version | head -n1)"
```

App status/logs:

```bash
just tokenplace-status
just tokenplace-debug-logs-env env=prod
```

Ingress/tunnel checks:

```bash
just cluster-status
just traefik-status
just cf-tunnel-debug
```
