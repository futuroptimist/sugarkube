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

## Promotion blockers

> Release blocker: web/TLS health is necessary but **not sufficient**. Production promotion is
> blocked until the staging relay-compute path has passed with an external desktop compute node
> and an end-to-end encrypted request/response.

Confirm every item before running `just tokenplace-oci-promote-prod`:

- [ ] **OCI chart freshness:** `helm show chart` and the recorded chart digest match the freshly
  published token.place chart for the approved release.
- [ ] **No duplicate env vars:** rendered production Deployment env validation passes for init and
  app containers. Duplicate env names are a release blocker.
- [ ] **XDG env present:** rendered Deployment includes chart-owned `XDG_CACHE_HOME`,
  `XDG_CONFIG_HOME`, and `XDG_DATA_HOME` values pointing at writable `/tmp` paths.
- [ ] **`/healthz` exempt from rate limit:** unauthenticated health checks stay below neither app
  nor edge rate limits and do not return HTTP 429/403.
- [ ] **Synthetic register/poll passes in staging:** API v1 synthetic registration and poll passed
  against the exact staging candidate image.
- [ ] **Desktop compute node registers in staging:** a real desktop compute node configured with
  staging `knownServers` / relay URL registered through the public staging hostname.
- [ ] **Registered compute node visible in staging:** the node appeared in `/healthz` and
  `/relay/diagnostics` safe routing metadata.
- [ ] **E2EE request/response passes in staging:** a client request completed through the relay and
  returned a decryptable response from the registered compute node.
- [ ] **Prod Cloudflare route configured:** `token.place` routes through Cloudflare Tunnel to
  production Traefik before cutover.

## Release evidence capture

Capture these commands during production promotion. They complement, but do not replace, the
staging evidence proving desktop compute registration and E2EE flow.

```bash
export TOKENPLACE_TAG=v0.1.0 # replace with the approved immutable release tag
export TOKENPLACE_CHART_VERSION="$(grep -E '^[0-9]+\.[0-9]+\.[0-9]+' docs/apps/tokenplace.version | head -n1)"
export TOKENPLACE_HOST=token.place

# chart digest / chart metadata
helm show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version "$TOKENPLACE_CHART_VERSION"
helm pull oci://ghcr.io/futuroptimist/charts/tokenplace --version "$TOKENPLACE_CHART_VERSION" --destination /tmp/tokenplace-chart
sha256sum "/tmp/tokenplace-chart/tokenplace-${TOKENPLACE_CHART_VERSION}.tgz"

# image tag and deployed image
printf 'approved image tag=%s\n' "$TOKENPLACE_TAG"
kubectl -n tokenplace get deploy/tokenplace -o jsonpath='{range .spec.template.spec.containers[*]}{.name}{"="}{.image}{"\n"}{end}'

# deployment YAML, including strategy.type: Recreate and env/XDG checks
kubectl -n tokenplace get deploy/tokenplace -o yaml > /tmp/tokenplace-prod-deployment.yaml
yq eval '.spec.strategy.type' /tmp/tokenplace-prod-deployment.yaml
yq eval '.spec.template.spec.containers[].env[] | select(.name | test("^XDG_"))' /tmp/tokenplace-prod-deployment.yaml

# production healthz and diagnostics evidence after smoke validation
curl -fsS "https://${TOKENPLACE_HOST}/healthz" | tee /tmp/tokenplace-prod-healthz.json
curl -fsS "https://${TOKENPLACE_HOST}/relay/diagnostics" | tee /tmp/tokenplace-prod-diagnostics.json

# relay logs after production smoke test
kubectl -n tokenplace logs deploy/tokenplace --tail=300 > /tmp/tokenplace-prod-relay-after-smoke.log
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

## Rollback options

Rollback reminders for the single-replica relay:

- Prefer rollback by immutable image tag when the chart is healthy but the relay image is bad.
- Use Helm revision rollback when the chart/rendered values are the suspected regression.
- Expect brief relay downtime and in-memory state loss during rollback because the Deployment
  intentionally uses `strategy.type: Recreate`. Existing compute-node registrations may need to
  reconnect and clients may need to retry.

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

## Emergency diagnostics

Use this emergency diagnostics copy-paste block when web health, compute-node registration,
diagnostics, TLS, or Cloudflare routing looks wrong. Check Cloudflare Security Events separately
for WAF, bot, rate-limit, or access-rule blocks if the relay logs do not show the rejected request.

```bash
just kubeconfig-env prod
export TOKENPLACE_HOST=token.place

# Kubernetes objects and rollout shape
kubectl -n tokenplace get deploy,rs,po,svc,ingress -o wide
kubectl -n tokenplace get certificates -o wide
kubectl -n tokenplace describe deploy/tokenplace
kubectl -n tokenplace describe ingress/tokenplace
kubectl -n tokenplace describe certificate --all

# Recent events, newest last
kubectl -n tokenplace get events --sort-by=.lastTimestamp | tail -n 80

# Relay logs: current and previous container, if a pod restarted
kubectl -n tokenplace logs deploy/tokenplace --tail=300
kubectl -n tokenplace logs deploy/tokenplace --previous --tail=300 || true

# Public edge/app probes
curl -vI "https://${TOKENPLACE_HOST}/"
curl -fsS "https://${TOKENPLACE_HOST}/healthz" || true
curl -fsS "https://${TOKENPLACE_HOST}/relay/diagnostics" || true

# Tunnel/certificate helpers
just cf-tunnel-debug
just cert-manager-status
```

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
