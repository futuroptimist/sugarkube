# k3s token.place runbook (prod)

Use this runbook for relay-only production token.place operations on Sugarkube.

## Scope and topology

- Release: `tokenplace`
- Namespace: `tokenplace`
- Chart: `oci://ghcr.io/futuroptimist/charts/tokenplace`
- Image: `ghcr.io/futuroptimist/tokenplace-relay`
- Runtime model: single relay replica + single worker + in-memory state.
- No in-cluster backend/GPU service is required.

## Values and host

- Base values: `docs/examples/tokenplace.values.dev.yaml`
- Production overlay: `docs/examples/tokenplace.values.prod.yaml`
- Production host default: `token.place`

## Promotion after staging sign-off

```bash
just tokenplace-oci-promote-prod tag=main-REPLACE_APPROVED_SHORTSHA
```

## Generic production upgrade (explicit Helm OCI)

```bash
just helm-oci-upgrade release=tokenplace namespace=tokenplace chart=oci://ghcr.io/futuroptimist/charts/tokenplace values=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.prod.yaml version_file=docs/apps/tokenplace.version default_tag=main-REPLACE_APPROVED_SHORTSHA
```

## Rollback options

1. **Rollback by redeploying previous immutable tag:**

   ```bash
   just helm-oci-upgrade release=tokenplace namespace=tokenplace chart=oci://ghcr.io/futuroptimist/charts/tokenplace values=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.prod.yaml version_file=docs/apps/tokenplace.version default_tag=main-REPLACE_PREVIOUS_SHORTSHA
   ```

2. **Rollback to previous Helm revision:**

   ```bash
   helm -n tokenplace history tokenplace
   just tokenplace-rollback release=tokenplace namespace=tokenplace revision=<known-good-revision>
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

- Production route is managed outside Helm.
- Route `token.place` to Traefik (typically `http://traefik.kube-system.svc.cluster.local:80`).
- Helper example: `just cf-tunnel-route host=token.place`

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
