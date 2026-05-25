# token.place relay on Sugarkube

This page documents relay-specific operations for the canonical token.place OCI deployment.

The local `apps/tokenplace-relay` chart is deprecated for steady-state operations. Use the
OCI chart and values files described below.

## Relay-only topology (current state)

Sugarkube runs relay-only token.place today:

- Runs: `relay.py` in k3s.
- Does not run: in-cluster backend service or GPU service.
- External compute remains outside the cluster (`server.py`, desktop Tauri app, Windows PCs,
  Apple Silicon Macs, Raspberry Pi compute nodes).
- Deployment is intentionally single-replica, single-worker, in-memory state.
- Pod restart/state loss is accepted for now.
- Multi-replica or shared-state architecture is future work and out of scope for this runbook.

## Canonical artifacts and pins

- Image: `ghcr.io/futuroptimist/tokenplace-relay`
- Chart: `oci://ghcr.io/futuroptimist/charts/tokenplace`
- Release: `tokenplace`
- Namespace: `tokenplace`
- Chart version pin: `docs/apps/tokenplace.version`
- Production approved image tag: `docs/apps/tokenplace.prod.tag`

## Values layering

- Base defaults: `docs/examples/tokenplace.values.dev.yaml`
- Staging overlay: `docs/examples/tokenplace.values.staging.yaml`
- Production overlay: `docs/examples/tokenplace.values.prod.yaml`

## Staging deployment quick commands

Prefer wrapper:

```bash
just tokenplace-oci-deploy env=staging tag=main-REPLACE_SHORTSHA
```

Equivalent explicit commands:

```bash
just helm-oci-install release=tokenplace namespace=tokenplace chart=oci://ghcr.io/futuroptimist/charts/tokenplace values=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.staging.yaml version_file=docs/apps/tokenplace.version default_tag=main-REPLACE_SHORTSHA
```

```bash
just helm-oci-upgrade release=tokenplace namespace=tokenplace chart=oci://ghcr.io/futuroptimist/charts/tokenplace values=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.staging.yaml version_file=docs/apps/tokenplace.version default_tag=main-REPLACE_SHORTSHA
```

## Validation commands

```bash
kubectl -n tokenplace get deploy,po,svc,ingress
kubectl -n tokenplace rollout status deploy/tokenplace --timeout=180s
curl -fsS https://staging.token.place/livez
curl -fsS https://staging.token.place/healthz
curl -fsS https://staging.token.place/
```

## Cloudflare tunnel guidance

Configure tunnel routes separately from Helm. Route hosts to Traefik service:
`http://traefik.kube-system.svc.cluster.local:80`.

Helpful commands when managing routes:

```bash
just cf-tunnel-route host=staging.token.place
just cf-tunnel-route host=token.place
```

See also [`docs/cloudflare_tunnel.md`](../cloudflare_tunnel.md).
