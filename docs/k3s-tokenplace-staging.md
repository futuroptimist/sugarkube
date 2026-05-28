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


## Promotion blockers before prod

> Release blocker: web/TLS health is necessary but not sufficient. Do **not** promote staging to
> production until the real relay-compute path below passes and the release evidence is captured.

- [ ] OCI chart freshness is proven for the pinned chart version and candidate immutable image tag.
- [ ] Rendered manifests contain no duplicate environment variables.
- [ ] XDG runtime environment is present from chart defaults; do not rely on manual
      `--set env.XDG_*=/tmp` incident-response overrides.
- [ ] `/livez`, `/healthz`, `/metrics`, `/relay/diagnostics`, and API v1 compute-node
      heartbeat/register/poll routes are exempt from global API rate limits; prove `/healthz` does
      not return HTTP 429 under repeated checks.
- [ ] Synthetic API v1 register/poll passes against `https://staging.token.place`.
- [ ] A real desktop compute node registers against staging; desktop `knownServers`/server settings
      must point at `https://staging.token.place`, not production.
- [ ] The registered compute node appears in both `/healthz` and `/relay/diagnostics`.
- [ ] End-to-end encrypted (E2EE) request/response succeeds through the registered compute node.
- [ ] The production Cloudflare route is configured before prod deploy:
      `token.place -> http://traefik.kube-system.svc.cluster.local:80`.

### Release evidence capture

Capture this evidence before declaring staging signed off. Keep the files with the release notes or
incident ticket so reviewers can distinguish "web health passed" from "relay release validated".

```bash
export TOKENPLACE_ENV=staging
export TOKENPLACE_HOST=staging.token.place
export TOKENPLACE_URL="https://${TOKENPLACE_HOST}"
export TOKENPLACE_TAG=main-deadbee # replace with the immutable staging candidate tag
export TOKENPLACE_VERSION="$(grep -E '^[0-9]+\.[0-9]+\.[0-9]+' docs/apps/tokenplace.version | head -n1)"
export TOKENPLACE_EVIDENCE_DIR="artifacts/tokenplace-${TOKENPLACE_ENV}-${TOKENPLACE_TAG}-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "${TOKENPLACE_EVIDENCE_DIR}"

helm show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version "${TOKENPLACE_VERSION}" \
  | tee "${TOKENPLACE_EVIDENCE_DIR}/chart.yaml"
helm pull oci://ghcr.io/futuroptimist/charts/tokenplace --version "${TOKENPLACE_VERSION}" \
  --destination "${TOKENPLACE_EVIDENCE_DIR}"
sha256sum "${TOKENPLACE_EVIDENCE_DIR}"/tokenplace-"${TOKENPLACE_VERSION}".tgz \
  | tee "${TOKENPLACE_EVIDENCE_DIR}/chart-digest.txt"

kubectl -n tokenplace get deploy tokenplace \
  -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}' \
  | tee "${TOKENPLACE_EVIDENCE_DIR}/image-tag.txt"
kubectl -n tokenplace get deploy tokenplace -o yaml \
  | tee "${TOKENPLACE_EVIDENCE_DIR}/deployment.yaml"

curl -fsS "${TOKENPLACE_URL}/healthz" | tee "${TOKENPLACE_EVIDENCE_DIR}/healthz.json"
curl -fsS "${TOKENPLACE_URL}/relay/diagnostics" \
  | tee "${TOKENPLACE_EVIDENCE_DIR}/relay-diagnostics.json"

# Run the desktop compute-node registration and E2EE request/response test now, then capture logs.
kubectl -n tokenplace logs deploy/tokenplace --since=15m --tail=500 \
  | tee "${TOKENPLACE_EVIDENCE_DIR}/relay-logs-after-compute-test.log"
```

### Promotion-gate command checklist

```bash
export TOKENPLACE_URL=https://staging.token.place

# Web/TLS checks: required but not sufficient for promotion.
curl -fsS "${TOKENPLACE_URL}/livez"
curl -fsS "${TOKENPLACE_URL}/healthz"
curl -fsS "${TOKENPLACE_URL}/metrics" >/tmp/tokenplace-staging-metrics.txt

# Rate-limit exemption smoke test for healthz. Any HTTP 429 blocks promotion.
for i in $(seq 1 20); do
  code="$(curl -sS -o /dev/null -w '%{http_code}' "${TOKENPLACE_URL}/healthz")"
  test "${code}" = 200 || { echo "healthz returned ${code} on attempt ${i}" >&2; exit 1; }
done

# Synthetic API v1 relay-compute checks. Use the current token.place synthetic payload/tooling;
# this runbook gate is not satisfied by web/TLS checks alone.
# Expected result: register succeeds, poll succeeds, and the synthetic node is visible in diagnostics.

# Real desktop compute node check. Point desktop knownServers/server settings at staging first.
curl -fsS "${TOKENPLACE_URL}/healthz" | jq .
curl -fsS "${TOKENPLACE_URL}/relay/diagnostics" | jq .

# E2EE check. Send a request through the registered desktop compute node and verify the encrypted
# response is returned to the client without exposing plaintext in relay logs or diagnostics.
kubectl -n tokenplace logs deploy/tokenplace --since=15m --tail=500
```

### Emergency diagnostics

This copy-pasteable emergency diagnostics block is for incidents where web health is misleading.
Use this block when staging looks healthy at `/`/TLS but compute-node registration, diagnostics, or
E2EE traffic fails. It gathers Kubernetes state, recent events, current and previous relay logs,
Cloudflare tunnel status, cert-manager status, and a reminder to inspect Cloudflare Security Events
for WAF/bot/rate-limit blocks before changing app code.

```bash
just kubeconfig-env staging
kubectl -n tokenplace get deploy,rs,po,svc,ingress,certificate -o wide
kubectl -n tokenplace describe deploy/tokenplace
kubectl -n tokenplace describe ingress/tokenplace
kubectl -n tokenplace describe certificate --all
kubectl -n tokenplace get events --sort-by=.lastTimestamp | tail -80
kubectl -n tokenplace logs deploy/tokenplace --since=30m --tail=500
kubectl -n tokenplace logs deploy/tokenplace --previous --tail=500 || true
just cf-tunnel-debug
just cert-manager-status
printf '%s\n' 'Check Cloudflare Security Events for token.place/staging.token.place WAF, bot, access, or rate-limit actions that could reject requests before they reach the app.'
```

## Rollback

Because token.place runs as a single replica with `strategy.type: Recreate`, expect a brief relay
outage during rollback while the old pod stops and the replacement pod starts. In-memory relay state
is lost. Prefer immutable image tag rollback when the chart is still correct; use Helm revision
rollback when the rendered release metadata needs to return to a known-good revision.

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
