# danielsmith.io on Sugarkube

This is the canonical Sugarkube deployment model for **danielsmith.io**.

## Topology and scope (current)

The danielsmith.io workload on Sugarkube is **static-site only**.

- The app is a static Vite + Three.js site.
- Sugarkube runs only the static web container.
- There is no API, backend, database, queue, GPU, compute node, or other stateful service in
  this deployment scope.
- Cloudflare Tunnel fronts Traefik, and Traefik routes traffic to the `danielsmith` Kubernetes
  Service.

Health and availability endpoints:

- `/livez`
- `/healthz`
- `/` (root page)

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

## Validation commands

```bash
kubectl -n danielsmith get deploy,po,svc,ingress
kubectl -n danielsmith rollout status deploy/danielsmith --timeout=180s
curl -fsS https://staging.danielsmith.io/livez
curl -fsS https://staging.danielsmith.io/healthz
curl -fsS https://staging.danielsmith.io/
```

For production validation, use the same checks against `https://danielsmith.io`.

## Cloudflare and ingress model

Cloudflare Tunnel and DNS configuration are external to Helm.

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
