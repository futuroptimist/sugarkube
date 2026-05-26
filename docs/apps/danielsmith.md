# danielsmith.io on Sugarkube

This is the canonical Sugarkube deployment model for `danielsmith.io`.

## Static-site topology (current scope)

Sugarkube currently runs **only** the static `danielsmith.io` web container (Vite + Three.js).

- **In-cluster (Sugarkube):** one static web Deployment exposed via Traefik ingress.
- **No in-cluster API/backend/database/queue/stateful service** is required.
- **No GPU or compute-node workload** is required for this app on Sugarkube.
- Cloudflare Tunnel fronts Traefik, and Traefik routes to the `danielsmith` Service.
- Health endpoints and root page:
  - `/livez`
  - `/healthz`
  - `/`

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

```bash
just helm-oci-install release=danielsmith namespace=danielsmith chart=oci://ghcr.io/futuroptimist/charts/danielsmith values=docs/examples/danielsmith.values.dev.yaml,docs/examples/danielsmith.values.staging.yaml version_file=docs/apps/danielsmith.version default_tag=main-REPLACE_SHORTSHA
```

```bash
just helm-oci-upgrade release=danielsmith namespace=danielsmith chart=oci://ghcr.io/futuroptimist/charts/danielsmith values=docs/examples/danielsmith.values.dev.yaml,docs/examples/danielsmith.values.staging.yaml version_file=docs/apps/danielsmith.version default_tag=main-REPLACE_SHORTSHA
```

Preferred env wrapper:

```bash
just danielsmith-oci-deploy env=staging tag=main-REPLACE_SHORTSHA
```

## Cloudflare and ingress model

Cloudflare Tunnel/DNS configuration is external to Helm.

- Route hostnames to Traefik, typically
  `http://traefik.kube-system.svc.cluster.local:80`.
- Helm chart deployment does **not** create Cloudflare routes.
- Configure routes explicitly:

```bash
just cf-tunnel-route host=staging.danielsmith.io
just cf-tunnel-route host=danielsmith.io
```

## Related runbooks

- Staging runbook: [`docs/k3s-danielsmith-staging.md`](../k3s-danielsmith-staging.md)
- Production runbook: [`docs/k3s-danielsmith-prod.md`](../k3s-danielsmith-prod.md)
