# k3s token.place runbook (staging)

Use this runbook for relay-only token.place staging deployments on Sugarkube.

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
- Values: `docs/examples/tokenplace.values.dev.yaml` + `docs/examples/tokenplace.values.staging.yaml`
- Default staging host: `staging.token.place`


## Pre-flight (before Step 1)

- Verify `docs/apps/tokenplace.version` remains pinned to `0.1.0`.
- Verify the `0.1.0` OCI chart exists only after token.place publishes the current chart.
- If `helm show chart ... --version 0.1.0` succeeds before the final token.place chart publish, confirm the chart is not stale before deploying.

```bash
helm show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version 0.1.0
```

## Promotion blockers

> Release blocker: web/TLS health is necessary but **not sufficient**. Do not promote a
> staging candidate to production until the real relay-compute path passes with an external
> desktop compute node and an end-to-end encrypted request/response.

Before production promotion, capture each item in the release notes or incident channel:

- [ ] **OCI chart freshness:** `helm show chart` reports the expected chart version and the
  registry digest matches the freshly published token.place chart, not a stale package.
- [ ] **No duplicate env vars:** rendered Deployment env validation passes for init and app
  containers. Duplicate env names are a release blocker.
- [ ] **XDG env present:** rendered Deployment includes chart-owned `XDG_CACHE_HOME`,
  `XDG_CONFIG_HOME`, and `XDG_DATA_HOME` values pointing at writable `/tmp` paths; do not rely
  on one-off manual Helm overrides.
- [ ] **`/healthz` exempt from rate limit:** repeated unauthenticated `GET /healthz` checks do
  not return HTTP 429/403 and remain usable for Kubernetes, Cloudflare, and operator probes.
- [ ] **Synthetic register/poll passes:** the API v1 synthetic registration and poll smoke test
  succeeds against `https://staging.token.place`.
- [ ] **Desktop compute node registers:** a real desktop compute node configured with staging
  `knownServers` / relay URL registers through the public staging hostname without HTTP 403 or
  pre-app rejection.
- [ ] **Registered compute node is visible:** the desktop node appears in both `/healthz` and
  `/relay/diagnostics` safe routing metadata.
- [ ] **E2EE request/response passes:** an end-to-end encrypted client request reaches the
  registered compute node and returns a decryptable response through the relay.
- [ ] **Prod Cloudflare route configured:** `token.place` is routed to the production Traefik
  service before the production deploy.

## Release evidence capture

Run these commands for the staging candidate and attach the output to the release record. Keep the
artifacts separate from basic web/TLS checks so reviewers can see the relay path was validated.

```bash
export TOKENPLACE_TAG=main-deadbee # replace with the immutable staging candidate tag
export TOKENPLACE_CHART_VERSION="$(grep -E '^[0-9]+\.[0-9]+\.[0-9]+' docs/apps/tokenplace.version | head -n1)"
export TOKENPLACE_HOST=staging.token.place

# chart digest / chart metadata
helm show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version "$TOKENPLACE_CHART_VERSION"
helm pull oci://ghcr.io/futuroptimist/charts/tokenplace --version "$TOKENPLACE_CHART_VERSION" --destination /tmp/tokenplace-chart
sha256sum "/tmp/tokenplace-chart/tokenplace-${TOKENPLACE_CHART_VERSION}.tgz"

# image tag and deployed image
printf 'candidate image tag=%s\n' "$TOKENPLACE_TAG"
kubectl -n tokenplace get deploy/tokenplace -o jsonpath='{range .spec.template.spec.containers[*]}{.name}{"="}{.image}{"\n"}{end}'

# deployment YAML, including strategy.type: Recreate and env/XDG checks
kubectl -n tokenplace get deploy/tokenplace -o yaml > /tmp/tokenplace-staging-deployment.yaml
yq eval '.spec.strategy.type' /tmp/tokenplace-staging-deployment.yaml
yq eval '.spec.template.spec.containers[].env[] | select(.name | test("^XDG_"))' /tmp/tokenplace-staging-deployment.yaml

# healthz and diagnostics evidence after synthetic + desktop compute tests
curl -fsS "https://${TOKENPLACE_HOST}/healthz" | tee /tmp/tokenplace-staging-healthz.json
curl -fsS "https://${TOKENPLACE_HOST}/relay/diagnostics" | tee /tmp/tokenplace-staging-diagnostics.json

# relay logs after compute-node registration and E2EE request/response
kubectl -n tokenplace logs deploy/tokenplace --tail=300 > /tmp/tokenplace-staging-relay-after-compute.log
```

## First install

```bash
just kubeconfig-env staging
TOKENPLACE_TAG=main-deadbee # replace with the immutable tag you want to deploy
just helm-oci-install release=tokenplace namespace=tokenplace chart=oci://ghcr.io/futuroptimist/charts/tokenplace values=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.staging.yaml version_file=docs/apps/tokenplace.version default_tag="$TOKENPLACE_TAG"
```

## Existing release upgrade

```bash
just kubeconfig-env staging
TOKENPLACE_TAG=main-deadbee # replace with the immutable tag you want to deploy
just helm-oci-upgrade release=tokenplace namespace=tokenplace chart=oci://ghcr.io/futuroptimist/charts/tokenplace values=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.staging.yaml version_file=docs/apps/tokenplace.version default_tag="$TOKENPLACE_TAG"
```

Preferred wrapper:

```bash
TOKENPLACE_TAG=main-deadbee # replace with the immutable tag you want to deploy
just tokenplace-oci-deploy env=staging tag="$TOKENPLACE_TAG"
```

## Validation

Render/contract checks (use immutable staging candidate tag):

```bash
helm show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version 0.1.0
helm template tokenplace oci://ghcr.io/futuroptimist/charts/tokenplace --version 0.1.0 --namespace tokenplace -f docs/examples/tokenplace.values.dev.yaml -f docs/examples/tokenplace.values.staging.yaml --set image.tag=main-deadbee > /tmp/tokenplace-staging-render.yaml
python3 - <<'PY'
import collections
import sys

try:
    import yaml
except ModuleNotFoundError:
    sys.exit("PyYAML is required for this render validation. Install it with: python3 -m pip install PyYAML")

with open("/tmp/tokenplace-staging-render.yaml", encoding="utf-8") as rendered:
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
grep -n "spec:" -A40 /tmp/tokenplace-staging-render.yaml | grep -n "tls"
grep -n "staging.token.place" /tmp/tokenplace-staging-render.yaml
grep -n "tokenplace-staging-tls" /tmp/tokenplace-staging-render.yaml
yq eval '. | select(.kind == "Deployment" and .metadata.name == "tokenplace") | .spec.strategy.type' /tmp/tokenplace-staging-render.yaml
```

Cluster/runtime checks:

```bash
kubectl -n tokenplace get deploy,po,svc,ingress
kubectl -n tokenplace rollout status deploy/tokenplace --timeout=180s
kubectl -n tokenplace get ingress tokenplace -o yaml
curl -vI https://staging.token.place/
curl -fsS https://staging.token.place/livez
curl -fsS https://staging.token.place/healthz
```

## Rollback

Rollback reminders for the single-replica relay:

- Prefer rollback by immutable image tag when the chart is healthy but the relay image is bad.
- Use Helm revision rollback when the chart/rendered values are the suspected regression.
- Expect brief relay downtime and in-memory state loss during rollback because the Deployment
  intentionally uses `strategy.type: Recreate`. Existing compute-node registrations may need to
  reconnect and clients may need to retry.

Rollback by immutable tag:

```bash
just kubeconfig-env staging
TOKENPLACE_PREVIOUS_TAG=main-deadbee # replace with the prior immutable tag
just helm-oci-upgrade release=tokenplace namespace=tokenplace chart=oci://ghcr.io/futuroptimist/charts/tokenplace values=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.staging.yaml version_file=docs/apps/tokenplace.version default_tag="$TOKENPLACE_PREVIOUS_TAG"
```

Rollback by Helm revision:

```bash
just kubeconfig-env staging
TOKENPLACE_REVISION=12 # replace with the known-good Helm revision
just tokenplace-rollback release=tokenplace namespace=tokenplace revision="$TOKENPLACE_REVISION"
```

## Emergency diagnostics

Use this emergency diagnostics copy-paste block when web health, compute-node registration,
diagnostics, TLS, or Cloudflare routing looks wrong. Check Cloudflare Security Events separately
for WAF, bot, rate-limit, or access-rule blocks if the relay logs do not show the rejected request.

```bash
just kubeconfig-env staging
export TOKENPLACE_HOST=staging.token.place

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

Cloudflare Tunnel still owns public hostname routing to Traefik; Helm does not manage Cloudflare routes. Route `staging.token.place` to Traefik,
typically `http://traefik.kube-system.svc.cluster.local:80`. Staging overlays render Ingress `spec.tls` because `ingress.tls.enabled: true`; `secretName` alone is not sufficient,
and this runbook assumes `cert-manager` and the referenced `ClusterIssuer` already exist.
One staging tunnel can serve multiple hostnames (for example `staging.democratized.space` and
`staging.token.place`) by routing both to Traefik; Traefik dispatches by `Host` header to the
correct Ingress.

`cf-tunnel-route` is for Cloudflare Tunnel hostname routing only. It is separate from the
Cloudflare DNS API token used by cert-manager DNS-01 challenges.

```bash
just cf-tunnel-route staging.token.place
just cf-tunnel-route host=staging.token.place
```

## cert-manager + Cloudflare DNS-01 (non-Flux clusters)

If your cluster does **not** run Flux, do not apply `platform/cert-manager` with Kustomize as-is. In staging we hit this exact failure mode:

- `kubectl apply -k platform/cert-manager` created the ConfigMap/issuers, then failed because `HelmRelease` was an unknown kind (Flux CRDs absent).
- The rendered issuer email remained literal `$(CERT_MANAGER_EMAIL)`, causing ACME `invalidContact`.

Use these recipes instead:

```bash
just cert-manager-install
just cert-manager-cloudflare-token-secret token="$CF_DNS_API_TOKEN"
just cert-manager-issuers-apply email="ops@token.place"
just cert-manager-status
```

Cloudflare DNS API token scope for cert-manager:

- `Zone -> DNS -> Edit`
- `Zone -> Zone -> Read`
- Include only required zones (at minimum `token.place`; include `democratized.space` too if the same token handles shared DSPACE cert issuance).

Validation commands:

```bash
kubectl get crd | grep cert-manager.io
kubectl get clusterissuer letsencrypt-staging letsencrypt-production
kubectl get certificate --all-namespaces
kubectl -n cert-manager get secret cloudflare-api-token
kubectl -n cert-manager logs deploy/cert-manager --tail=100
```

> ⚠️ During early staging we used manual Helm `--set env.XDG_CACHE_HOME=/tmp --set env.XDG_CONFIG_HOME=/tmp --set env.XDG_DATA_HOME=/tmp` overrides to pass read-only filesystem startup checks. Remove those manual overrides now that chart defaults own the XDG `/tmp` paths.


## 0.1.0 release alignment

- OCI chart package version: `0.1.0`
- Chart `appVersion`: `0.1.0`
- token.place Git tag: `v0.1.0`
- Release image tag after final tag push: `ghcr.io/futuroptimist/tokenplace-relay:v0.1.0`
- Staging candidate tag before final tag push: `main-<shortsha>`