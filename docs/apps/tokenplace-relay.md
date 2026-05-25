# token.place relay on Sugarkube

This is the concrete relay-only runbook for Sugarkube.

## Current topology

Sugarkube runs only `token.place` `relay.py`.

- No in-cluster backend service.
- No in-cluster GPU service.
- External compute nodes remain external (`server.py`, desktop Tauri app, Windows PCs,
  Apple Silicon Macs, Raspberry Pi compute nodes, and related workers).
- Runtime shape: single relay replica, single worker, in-memory state.
- State loss on pod death is accepted at this stage.
- Future multi-replica/stateful architecture is out of scope for this runbook.

## Canonical artifacts

- Image: `ghcr.io/futuroptimist/tokenplace-relay`
- Chart: `oci://ghcr.io/futuroptimist/charts/tokenplace`
- Release: `tokenplace`
- Namespace: `tokenplace`
- Version pin: `docs/apps/tokenplace.version`
- Prod approved tag pin: `docs/apps/tokenplace.prod.tag`

## Values model

- Base values: `docs/examples/tokenplace.values.dev.yaml`
- Staging overlay: `docs/examples/tokenplace.values.staging.yaml`
- Prod overlay: `docs/examples/tokenplace.values.prod.yaml`

Default hosts:

- Staging host: `staging.token.place`
- Prod host: `token.place`

## Staging deployment

### First install

```bash
just helm-oci-install release=tokenplace namespace=tokenplace chart=oci://ghcr.io/futuroptimist/charts/tokenplace values=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.staging.yaml version_file=docs/apps/tokenplace.version default_tag=main-REPLACE_SHORTSHA
```

### Existing release upgrade

```bash
just helm-oci-upgrade release=tokenplace namespace=tokenplace chart=oci://ghcr.io/futuroptimist/charts/tokenplace values=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.staging.yaml version_file=docs/apps/tokenplace.version default_tag=main-REPLACE_SHORTSHA
```

### Preferred wrapper

```bash
just tokenplace-oci-deploy env=staging tag=main-REPLACE_SHORTSHA
```

### Staging validation

```bash
kubectl -n tokenplace get deploy,po,svc,ingress
kubectl -n tokenplace rollout status deploy/tokenplace --timeout=180s
curl -fsS https://staging.token.place/livez
curl -fsS https://staging.token.place/healthz
curl -fsS https://staging.token.place/
```

## Production rollout and rollback

### Promote approved staging tag

```bash
just tokenplace-oci-promote-prod tag=main-REPLACE_APPROVED_SHORTSHA
```

### Generic production upgrade

```bash
just helm-oci-upgrade release=tokenplace namespace=tokenplace chart=oci://ghcr.io/futuroptimist/charts/tokenplace values=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.prod.yaml version_file=docs/apps/tokenplace.version default_tag=main-REPLACE_APPROVED_SHORTSHA
```

### Roll back to previous immutable tag

```bash
just helm-oci-upgrade release=tokenplace namespace=tokenplace chart=oci://ghcr.io/futuroptimist/charts/tokenplace values=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.prod.yaml version_file=docs/apps/tokenplace.version default_tag=main-REPLACE_PREVIOUS_SHORTSHA
```

### Roll back Helm revision

```bash
just tokenplace-rollback
```

### Production validation

```bash
kubectl -n tokenplace get deploy,po,svc,ingress
kubectl -n tokenplace rollout status deploy/tokenplace --timeout=180s
curl -fsS https://token.place/livez
curl -fsS https://token.place/healthz
curl -fsS https://token.place/
```

## Cloudflare Tunnel guidance

Cloudflare Tunnel/DNS is configured outside Helm.

- Route hostnames to Traefik, typically `http://traefik.kube-system.svc.cluster.local:80`.
- Helm chart deployment does not create Cloudflare routes.
- Suggested helper commands (if configured in your environment):

```bash
just cf-tunnel-route host=staging.token.place
just cf-tunnel-route host=token.place
```

## Troubleshooting

### GHCR auth and chart availability

```bash
helm registry login ghcr.io
helm show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version "$(grep -E '^[0-9]+\.[0-9]+\.[0-9]+' docs/apps/tokenplace.version | head -n1)"
```

### App status and logs

```bash
just tokenplace-status
just tokenplace-debug-logs-env env=staging
just tokenplace-debug-logs-env env=prod
```

### Ingress, Traefik, and tunnel diagnostics

```bash
just cluster-status
just traefik-status
just cf-tunnel-debug
```
