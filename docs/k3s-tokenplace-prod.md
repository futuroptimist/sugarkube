# k3s token.place runbook (prod)

Use this runbook for relay-only token.place production deployments on Sugarkube.

## Topology and scope

- Sugarkube runs only token.place relay (`relay.py`).
- No in-cluster backend/GPU service is required.
- Compute nodes remain external (`server.py`, Tauri desktop app, Windows PCs, Apple Silicon Macs,
  Raspberry Pi compute nodes, etc.).
- Runtime model is strict single replica + single Gunicorn worker + in-memory state.
- Rollout strategy remains strict `strategy.type: Recreate`.
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

After final token.place Git tag push, promote the release image tag `ghcr.io/futuroptimist/tokenplace-relay:v0.1.0`.

```bash
TOKENPLACE_TAG=v0.1.0
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
helm show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version 0.1.0
helm template tokenplace oci://ghcr.io/futuroptimist/charts/tokenplace --version 0.1.0 --namespace tokenplace -f docs/examples/tokenplace.values.dev.yaml -f docs/examples/tokenplace.values.prod.yaml --set image.tag=v0.1.0 > /tmp/tokenplace-prod-render.yaml
grep -n "tls:" -A8 /tmp/tokenplace-prod-render.yaml
grep -n "token.place" /tmp/tokenplace-prod-render.yaml
grep -n "tokenplace-prod-tls" /tmp/tokenplace-prod-render.yaml
grep -n "type: Recreate" /tmp/tokenplace-prod-render.yaml
kubectl -n tokenplace get ingress tokenplace -o yaml
kubectl -n tokenplace rollout status deploy/tokenplace --timeout=180s
curl -vI https://token.place/
```

## Rollback options

Rollback by immutable tag:

```bash
just kubeconfig-env prod
TOKENPLACE_PREVIOUS_TAG=main-deadbee # replace with the prior immutable tag
just helm-oci-upgrade release=tokenplace namespace=tokenplace chart=oci://ghcr.io/futuroptimist/charts/tokenplace values=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.prod.yaml version_file=docs/apps/tokenplace.version default_tag="$TOKENPLACE_PREVIOUS_TAG"
```

Rollback by Helm revision:

```bash
just kubeconfig-env prod
TOKENPLACE_REVISION=12 # replace with the known-good Helm revision
just tokenplace-rollback release=tokenplace namespace=tokenplace revision="$TOKENPLACE_REVISION"
```

## Cloudflare tunnel routing (external to Helm)

Cloudflare Tunnel still owns public hostname routing. Helm does not manage Cloudflare routes. Route `token.place` to Traefik, typically `http://traefik.kube-system.svc.cluster.local:80`. Production values now render Kubernetes Ingress `spec.tls`, assuming cert-manager and a compatible ClusterIssuer already exist.

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
