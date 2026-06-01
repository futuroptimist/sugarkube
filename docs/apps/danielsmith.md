# danielsmith.io on Sugarkube

This app follows the shared [Sugarkube app deployment contract](../app_deployment_contract.md),
including the artifact model, immutable tag policy, and future generic `just app-*` command shape.

This is the canonical Sugarkube deployment model for `danielsmith.io`.

## Topology and scope (static-site only)

`danielsmith.io` is a static Vite + Three.js site. Sugarkube runs only the static web container.

- **In-cluster (Sugarkube):** one static web deployment exposed through Traefik ingress.
- **No in-cluster API/backend/database/queue/GPU/compute node/stateful service** is required.
- **Public ingress path:** Cloudflare Tunnel fronts Traefik, and Traefik routes to the
  `danielsmith` Kubernetes Service.
- **Health/availability endpoints:** `/livez`, `/healthz`.
- **Root page:** `/`.

## Artifact model (canonical)

- Image: `ghcr.io/futuroptimist/danielsmith.io`
- Chart: `oci://ghcr.io/futuroptimist/charts/danielsmith`
- Helm release: `danielsmith`
- Namespace: `danielsmith`
- Chart version pin file: `docs/apps/danielsmith.version`
- Production approved tag pin: `docs/apps/danielsmith.prod.tag`

## Values model

- Base: `docs/examples/danielsmith.values.dev.yaml`
- Staging overlay: `docs/examples/danielsmith.values.staging.yaml`
- Production overlay: `docs/examples/danielsmith.values.prod.yaml`

Default hosts:

- Staging: `staging.danielsmith.io`
- Production: `danielsmith.io`

## Core deployment commands

First install (or install-or-upgrade) with generic helper:

```bash
just kubeconfig-env staging
DANIELSMITH_TAG=main-REPLACE_SHORTSHA # replace with the immutable GHCR image tag to deploy
just helm-oci-install release=danielsmith namespace=danielsmith chart=oci://ghcr.io/futuroptimist/charts/danielsmith values=docs/examples/danielsmith.values.dev.yaml,docs/examples/danielsmith.values.staging.yaml version_file=docs/apps/danielsmith.version default_tag="$DANIELSMITH_TAG"
```

Existing release upgrade with generic helper:

```bash
just kubeconfig-env staging
DANIELSMITH_TAG=main-REPLACE_SHORTSHA # replace with the immutable GHCR image tag to deploy
just helm-oci-upgrade release=danielsmith namespace=danielsmith chart=oci://ghcr.io/futuroptimist/charts/danielsmith values=docs/examples/danielsmith.values.dev.yaml,docs/examples/danielsmith.values.staging.yaml version_file=docs/apps/danielsmith.version default_tag="$DANIELSMITH_TAG"
```

Preferred environment wrapper:

```bash
DANIELSMITH_TAG=main-REPLACE_SHORTSHA # replace with the immutable GHCR image tag to deploy
just danielsmith-oci-deploy env=staging tag="$DANIELSMITH_TAG"
```

## Validation commands

```bash
kubectl -n danielsmith get deploy,po,svc,ingress
kubectl -n danielsmith rollout status deploy/danielsmith --timeout=180s
curl -fsS https://staging.danielsmith.io/livez
curl -fsS https://staging.danielsmith.io/healthz
curl -fsS https://staging.danielsmith.io/
```

For production validation, use the same checks against `https://danielsmith.io`.

## Cloudflare Tunnel and ingress model

Cloudflare Tunnel/DNS configuration is external to Helm.

- Route hostnames to Traefik, typically
  `http://traefik.kube-system.svc.cluster.local:80`.
- Helm chart deployment does **not** create Cloudflare routes.
- Configure staging and prod routes explicitly:

```bash
just cf-tunnel-route host=staging.danielsmith.io
just cf-tunnel-route host=danielsmith.io
```

## Related runbooks

- Staging runbook: [`docs/k3s-danielsmith-staging.md`](../k3s-danielsmith-staging.md)
- Production runbook: [`docs/k3s-danielsmith-prod.md`](../k3s-danielsmith-prod.md)
