# k3s token.place runbook (staging)

Use this runbook to deploy relay-only token.place to staging on Sugarkube.

## Scope and topology

- Release: `tokenplace`
- Namespace: `tokenplace`
- Chart: `oci://ghcr.io/futuroptimist/charts/tokenplace`
- Image: `ghcr.io/futuroptimist/tokenplace-relay`
- Runtime model: single relay replica + single worker + in-memory state.
- No in-cluster backend/GPU service is required.

## Values and host

- Base values: `docs/examples/tokenplace.values.dev.yaml`
- Staging overlay: `docs/examples/tokenplace.values.staging.yaml`
- Staging host default: `staging.token.place`

## Prerequisites

- Cloudflare Tunnel route for `staging.token.place` points to Traefik
  (`http://traefik.kube-system.svc.cluster.local:80`).
- GHCR auth is available for Helm OCI pull when required.

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

- GHCR auth + chart check:

  ```bash
  helm registry login ghcr.io
  helm show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version "$(grep -E '^[0-9]+\.[0-9]+\.[0-9]+' docs/apps/tokenplace.version | head -n1)"
  ```

- App diagnostics:

  ```bash
  just tokenplace-status
  just tokenplace-debug-logs-env env=staging
  ```

- Ingress/Tunnel diagnostics:

  ```bash
  just cluster-status
  just traefik-status
  just cf-tunnel-debug
  ```
