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

Production promotion is blocked until staging proves the actual relay-compute path, not just web
health or TLS readiness. Deployment Ready `1/1`, certificate Ready, `/livez`, `/healthz`, `/`,
`/metrics`, and synthetic register/poll checks are necessary but not sufficient.

### Promotion blockers

- [ ] **OCI chart freshness:** chart metadata and the captured chart digest match the intended
  token.place release candidate.
- [ ] **No duplicate env vars:** prod render validation exits cleanly with no duplicate env names.
- [ ] **XDG env present:** prod Deployment env includes chart-owned XDG `/tmp` paths; do not depend
  on one-off Helm `--set env.XDG_*=/tmp` overrides.
- [ ] **`/healthz` exempt from rate limit:** repeated `/healthz` probes succeed without consuming or
  tripping global API rate limits.
- [ ] **Synthetic register/poll passes:** API v1 synthetic compute-node register/poll succeeds
  against staging.
- [ ] **Desktop compute node registers:** a real desktop compute node whose `knownServers` targets
  staging registers through `https://staging.token.place`.
- [ ] **Registered compute node is visible:** the node appears in staging `/healthz` and
  `/relay/diagnostics`.
- [ ] **E2EE request/response passes:** staging completes an end-to-end encrypted request/response
  through the registered compute node.
- [ ] **Prod Cloudflare route configured:** `token.place` routes to Traefik before promotion.

Only after every blocker is checked may production be promoted:

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
import collections
import sys

try:
    import yaml
except ModuleNotFoundError:
    sys.exit("PyYAML is required for this render validation. Install it with: python3 -m pip install PyYAML")

with open("/tmp/tokenplace-prod-render.yaml", encoding="utf-8") as rendered:
    docs = list(yaml.safe_load_all(rendered))

try:
    deploy = next(
        d
        for d in docs
        if d and d.get("kind") == "Deployment" and d.get("metadata", {}).get("name") == "tokenplace"
    )
except StopIteration:
    sys.exit("tokenplace Deployment not found in rendered manifest")

pod_spec = deploy["spec"]["template"]["spec"]
for container_type, containers in (
    ("init", pod_spec.get("initContainers", [])),
    ("app", pod_spec.get("containers", [])),
):
    for container in containers:
        names = [item["name"] for item in container.get("env", []) if "name" in item]
        dupes = [name for name, count in collections.Counter(names).items() if count > 1]
        if dupes:
            sys.exit(f"duplicate env names found: {container_type}:{container.get('name', '<unnamed>')}: {dupes}")
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

## Release evidence capture

Capture evidence during the promotion window and attach it to the release notes or incident channel:

```bash
CHART_VERSION="$(grep -E '^[0-9]+\.[0-9]+\.[0-9]+' docs/apps/tokenplace.version | head -n1)"
TOKENPLACE_TAG=v0.1.0 # replace with the immutable production tag
helm show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version "$CHART_VERSION"
helm pull oci://ghcr.io/futuroptimist/charts/tokenplace --version "$CHART_VERSION" \
  --destination /tmp/tokenplace-chart-evidence
sha256sum /tmp/tokenplace-chart-evidence/tokenplace-"$CHART_VERSION".tgz # chart digest
printf 'image tag: ghcr.io/futuroptimist/tokenplace-relay:%s\n' "$TOKENPLACE_TAG"
kubectl -n tokenplace get deploy tokenplace -o yaml > /tmp/tokenplace-prod-deployment.yaml
curl -fsS https://token.place/healthz | tee /tmp/tokenplace-prod-healthz.json
curl -fsS https://token.place/relay/diagnostics | tee /tmp/tokenplace-prod-diagnostics.json
# Run the desktop compute-node registration and E2EE request/response test now.
kubectl -n tokenplace logs deploy/tokenplace --tail=200 > /tmp/tokenplace-prod-relay-after-compute.log
```

## Emergency diagnostics

Copy/paste this block if production web health passes but compute-node registration, diagnostics, or
E2EE relay traffic fails:

```bash
just kubeconfig-env prod
kubectl -n tokenplace get deployments,replicasets,pods,services,ingress,certificates -o wide
kubectl -n tokenplace describe deploy tokenplace
kubectl -n tokenplace describe ingress tokenplace
kubectl -n tokenplace get events --sort-by=.lastTimestamp | tail -n 80
kubectl -n tokenplace logs deploy/tokenplace --tail=300
kubectl -n tokenplace logs deploy/tokenplace --previous --tail=300 || true
just tokenplace-debug-logs-env env=prod
just cf-tunnel-debug
just cert-manager-status
```

Also check Cloudflare Security Events for `token.place` around the failed registration time. A
Cloudflare WAF/rate-limit/challenge event can reject requests before the relay application logs
anything.

## Rollback options

Rollback by immutable image tag when the prior good container image is known:

```bash
just kubeconfig-env prod
TOKENPLACE_PREVIOUS_TAG=main-deadbee # replace with the prior immutable tag
just helm-oci-upgrade release=tokenplace namespace=tokenplace chart=oci://ghcr.io/futuroptimist/charts/tokenplace values=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.prod.yaml version_file=docs/apps/tokenplace.version default_tag="$TOKENPLACE_PREVIOUS_TAG"
```

Rollback by Helm revision when the prior good release revision is known:

```bash
just kubeconfig-env prod
TOKENPLACE_REVISION=12 # replace with the known-good Helm revision
just tokenplace-rollback release=tokenplace namespace=tokenplace revision="$TOKENPLACE_REVISION"
```

Both rollback paths restart the only relay pod because the Deployment strategy is `Recreate`. Expect
a short downtime window and loss of in-memory relay registrations while the single replacement pod
starts.

## Cloudflare tunnel routing (external to Helm)

Cloudflare Tunnel still owns public hostname routing to Traefik; Helm does not manage Cloudflare routes. Route `token.place` to Traefik,
typically `http://traefik.kube-system.svc.cluster.local:80`. Production overlays render Ingress `spec.tls` because `ingress.tls.enabled: true`; `secretName` alone is not sufficient,
and this runbook assumes `cert-manager` and the referenced `ClusterIssuer` already exist.
One tunnel per environment can carry multiple app hostnames by routing them all to Traefik, with
Traefik selecting the target backend by `Host` header.

`cf-tunnel-route` configures Cloudflare Tunnel hostname routing. It does not configure the
cert-manager Cloudflare DNS token used for ACME DNS-01.

```bash
just cf-tunnel-route token.place
just cf-tunnel-route host=token.place
```

## cert-manager + Cloudflare DNS-01 (non-Flux clusters)

For non-Flux production clusters, use the same manual Helm + issuer flow validated during staging:

```bash
just cert-manager-install
just cert-manager-cloudflare-token-secret token="$CF_DNS_API_TOKEN"
just cert-manager-issuers-apply email="ops@token.place"
just cert-manager-status
```

Do not reuse the tunnel token (`CF_TUNNEL_TOKEN`) for DNS-01. cert-manager needs a separate Cloudflare DNS API token scoped to:

- `Zone -> DNS -> Edit`
- `Zone -> Zone -> Read`
- specific required zones (`token.place`, and `democratized.space` if shared issuance is in scope).

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
