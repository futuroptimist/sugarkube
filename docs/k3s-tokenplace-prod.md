# k3s token.place runbook (prod)

Use this runbook for relay-only token.place production deployments on Sugarkube.

## Topology and scope

- Sugarkube runs only token.place relay (`relay.py`).
- No in-cluster backend/GPU service is required.
- Compute nodes remain external (`server.py`, Tauri desktop app, Windows PCs, Apple Silicon Macs,
  Raspberry Pi compute nodes, etc.).
- Runtime model is single replica + single Gunicorn worker + in-memory state; verify the rendered Kubernetes Deployment contract includes `spec.strategy.type: Recreate` before rollout.
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

## Pre-flight (before Step 1)

- Verify `docs/apps/tokenplace.version` remains pinned to `0.1.0`.
- Verify the `0.1.0` OCI chart exists only after token.place publishes the current chart.
- If `helm show chart ... --version 0.1.0` succeeds before the final token.place chart publish, confirm the chart is not stale before deploying.

```bash
helm show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version 0.1.0
```

## Promotion after staging sign-off

```bash
TOKENPLACE_TAG=v0.1.0 # use final release tag after token.place Git tag push
just tokenplace-oci-promote-prod tag="$TOKENPLACE_TAG"
```

## Generic production upgrade

Select the production kube context first (or use the wrapper above):

```bash
just kubeconfig-env prod
```

Then run the generic OCI helper:

```bash
TOKENPLACE_TAG=v0.1.0 # use final release tag after token.place Git tag push
just helm-oci-upgrade release=tokenplace namespace=tokenplace chart=oci://ghcr.io/futuroptimist/charts/tokenplace values=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.prod.yaml version_file=docs/apps/tokenplace.version default_tag="$TOKENPLACE_TAG"
```

## Validation

Render/contract checks:

```bash
helm show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version 0.1.0
helm template tokenplace oci://ghcr.io/futuroptimist/charts/tokenplace --version 0.1.0 --namespace tokenplace -f docs/examples/tokenplace.values.dev.yaml -f docs/examples/tokenplace.values.prod.yaml --set image.tag=v0.1.0 > /tmp/tokenplace-prod-render.yaml
python3 - <<'PY'
import collections, yaml
docs = list(yaml.safe_load_all(open("/tmp/tokenplace-prod-render.yaml")))
deploy = next(d for d in docs if d and d.get("kind") == "Deployment")
env = deploy["spec"]["template"]["spec"]["containers"][0]["env"]
names = [item["name"] for item in env]
dupes = [name for name, count in collections.Counter(names).items() if count > 1]
assert not dupes, dupes
PY
grep -n "spec:" -A40 /tmp/tokenplace-prod-render.yaml | grep -n "tls"
grep -n "token.place" /tmp/tokenplace-prod-render.yaml
grep -n "tokenplace-prod-tls" /tmp/tokenplace-prod-render.yaml
yq eval '. | select(.kind == "Deployment" and .metadata.name == "tokenplace") | .spec.strategy.type' /tmp/tokenplace-prod-render.yaml
```

Cluster/runtime checks:

```bash
kubectl -n tokenplace get deploy,po,svc,ingress
kubectl -n tokenplace rollout status deploy/tokenplace --timeout=180s
kubectl -n tokenplace get ingress tokenplace -o yaml
curl -vI https://token.place/
curl -fsS https://token.place/livez
curl -fsS https://token.place/healthz
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

Cloudflare Tunnel still owns public hostname routing to Traefik; Helm does not manage Cloudflare routes. Route `token.place` to Traefik,
typically `http://traefik.kube-system.svc.cluster.local:80`. Production overlays render Ingress `spec.tls` because `ingress.tls.enabled: true`; `secretName` alone is not sufficient,
and this runbook assumes `cert-manager` and the referenced `ClusterIssuer` already exist.

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


## 0.1.0 release alignment

- OCI chart package version: `0.1.0`
- Chart `appVersion`: `0.1.0`
- token.place Git tag: `v0.1.0`
- Release image tag after final tag push: `ghcr.io/futuroptimist/tokenplace-relay:v0.1.0`
- Staging candidate tag before final tag push: `main-<shortsha>`
