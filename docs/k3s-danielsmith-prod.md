# k3s danielsmith.io runbook (prod)

Use this runbook for production deployments of the static `danielsmith.io` site on Sugarkube.

## Topology and scope

- `danielsmith.io` is a static Vite + Three.js workload.
- Sugarkube runs only the static web container.
- No in-cluster API/backend/database/queue/GPU/compute node/stateful service is required.
- Cloudflare Tunnel fronts Traefik; Traefik routes traffic to the `danielsmith` Service.
- Probe/application endpoints: `/livez`, `/healthz`, and `/`.

## Artifact and values contract

- Chart: `oci://ghcr.io/futuroptimist/charts/danielsmith`
- Image: `ghcr.io/futuroptimist/danielsmith.io`
- Release: `danielsmith`
- Namespace: `danielsmith`
- Version pin file: `docs/apps/danielsmith.version`
- Approved prod tag file: `docs/apps/danielsmith.prod.tag`
- Values: `docs/examples/danielsmith.values.dev.yaml` + `docs/examples/danielsmith.values.prod.yaml`
- Default production host: `danielsmith.io`

## First install

Always select the production kube context before running the generic Helm install command.

```bash
just kubeconfig-env prod
DANIELSMITH_APPROVED_TAG=main-REPLACE_APPROVED_SHORTSHA # replace with the approved immutable GHCR image tag
just helm-oci-install release=danielsmith namespace=danielsmith chart=oci://ghcr.io/futuroptimist/charts/danielsmith values=docs/examples/danielsmith.values.dev.yaml,docs/examples/danielsmith.values.prod.yaml version_file=docs/apps/danielsmith.version default_tag="$DANIELSMITH_APPROVED_TAG"
```

## Promotion after staging sign-off

```bash
DANIELSMITH_APPROVED_TAG=main-REPLACE_APPROVED_SHORTSHA # replace with the approved immutable GHCR image tag
just danielsmith-oci-promote-prod tag="$DANIELSMITH_APPROVED_TAG"
```

## Generic production upgrade

```bash
just kubeconfig-env prod
DANIELSMITH_APPROVED_TAG=main-REPLACE_APPROVED_SHORTSHA # replace with the approved immutable GHCR image tag
just helm-oci-upgrade release=danielsmith namespace=danielsmith chart=oci://ghcr.io/futuroptimist/charts/danielsmith values=docs/examples/danielsmith.values.dev.yaml,docs/examples/danielsmith.values.prod.yaml version_file=docs/apps/danielsmith.version default_tag="$DANIELSMITH_APPROVED_TAG"
```

## Validation

```bash
kubectl -n danielsmith get deploy,po,svc,ingress
kubectl -n danielsmith rollout status deploy/danielsmith --timeout=180s
curl -fsS https://danielsmith.io/livez
curl -fsS https://danielsmith.io/healthz
curl -fsS https://danielsmith.io/
```

## Rollback options

Rollback by immutable tag:

```bash
just kubeconfig-env prod
DANIELSMITH_PREVIOUS_APPROVED_TAG=main-REPLACE_PREVIOUS_APPROVED_SHORTSHA # replace with the previous approved immutable GHCR image tag
just helm-oci-upgrade release=danielsmith namespace=danielsmith chart=oci://ghcr.io/futuroptimist/charts/danielsmith values=docs/examples/danielsmith.values.dev.yaml,docs/examples/danielsmith.values.prod.yaml version_file=docs/apps/danielsmith.version default_tag="$DANIELSMITH_PREVIOUS_APPROVED_TAG"
```

Rollback by Helm revision:

`tokenplace-rollback` is the repository's existing parameterized Helm rollback helper, even though the recipe name is token.place-scoped.

```bash
just kubeconfig-env prod
DANIELSMITH_REVISION=12 # replace with the known-good Helm revision
just tokenplace-rollback release=danielsmith namespace=danielsmith revision="$DANIELSMITH_REVISION"
```

## Cloudflare tunnel routing (external to Helm)

Cloudflare routes are configured outside the chart. Route `danielsmith.io` to Traefik,
typically `http://traefik.kube-system.svc.cluster.local:80`.

```bash
just cf-tunnel-route host=danielsmith.io
```

## Troubleshooting

GHCR auth/chart checks:

```bash
echo "$GHCR_TOKEN" | helm registry login ghcr.io -u "$GHCR_USER" --password-stdin
helm show chart oci://ghcr.io/futuroptimist/charts/danielsmith --version "$(grep -E '^[0-9]+\.[0-9]+\.[0-9]+' docs/apps/danielsmith.version | head -n1)"
```

App status/logs:

```bash
just danielsmith-status
just danielsmith-debug-logs-env env=prod
```

Ingress/tunnel checks:

```bash
just cluster-status
just traefik-status
just cf-tunnel-debug
```
