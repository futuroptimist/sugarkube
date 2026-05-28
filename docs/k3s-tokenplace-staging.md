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

## Promotion blockers

> **Release blocker:** staging is not validated by web/TLS health alone. Do not promote this
> token.place build to production until the real relay-compute path below passes end-to-end.

Check every item before approving prod promotion:

- [ ] OCI chart freshness is proven with `helm show chart`; the chart digest/version was published
  for this candidate and is not a stale `0.1.0` package.
- [ ] Render validation finds no duplicate environment variables in any init/app container.
- [ ] Rendered Deployment keeps XDG runtime/cache/config/data homes on writable `/tmp` chart
  defaults, with no one-off Sugarkube `--set env.XDG_*=/tmp` drift.
- [ ] `/healthz` is exempt from token.place global API rate limits; repeated probes return 200 and
  do not mask Cloudflare 403/pre-app rejection behavior.
- [ ] Synthetic API v1 compute-node register/poll passes against `https://staging.token.place`.
- [ ] A real desktop compute node has `staging.token.place` in its `knownServers`/server list,
  registers successfully, and does not silently fall back to production.
- [ ] The registered desktop compute node appears in both `/healthz` and `/relay/diagnostics`.
- [ ] An E2EE request/response succeeds through the registered staging compute node.
- [ ] The production Cloudflare route for `token.place` is configured before prod cutover, but is
  still treated as external to Helm/cert-manager.

### Release evidence capture

Capture this evidence with the staging candidate tag before promotion review. Run the synthetic
register/poll, confirm desktop compute-node registration, and complete the E2EE request/response
before saving `/healthz`, `/relay/diagnostics`, or relay logs so those artifacts prove the
registered desktop compute node is visible after the real relay-compute path passes:

```bash
just kubeconfig-env staging
TOKENPLACE_TAG=main-deadbee # replace with the immutable candidate tag
TOKENPLACE_HOST=staging.token.place
TOKENPLACE_CHART_VERSION="$(grep -E '^[0-9]+\.[0-9]+\.[0-9]+' docs/apps/tokenplace.version | head -n1)"

helm show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version "$TOKENPLACE_CHART_VERSION"
helm pull oci://ghcr.io/futuroptimist/charts/tokenplace --version "$TOKENPLACE_CHART_VERSION" --destination /tmp
sha256sum "/tmp/tokenplace-${TOKENPLACE_CHART_VERSION}.tgz" # chart digest evidence
printf 'image tag: ghcr.io/futuroptimist/tokenplace-relay:%s\n' "$TOKENPLACE_TAG"
kubectl -n tokenplace get deploy tokenplace -o yaml > /tmp/tokenplace-staging-deployment.yaml
# First run synthetic register/poll, desktop compute-node registration, and the E2EE flow.
# Then capture health, diagnostics, and relay logs as post-compute-path evidence:
curl -fsS "https://${TOKENPLACE_HOST}/healthz" | tee /tmp/tokenplace-staging-healthz.json
curl -fsS "https://${TOKENPLACE_HOST}/relay/diagnostics" | tee /tmp/tokenplace-staging-diagnostics.json
kubectl -n tokenplace logs deploy/tokenplace --since=30m --tail=500 | tee /tmp/tokenplace-staging-relay-after-compute.log
```

### Emergency diagnostics

This emergency diagnostics command block is copy-pasteable. Run it when staging looks healthy at `/` or TLS but relay registration/E2EE fails:

```bash
just kubeconfig-env staging
TOKENPLACE_HOST=staging.token.place

kubectl -n tokenplace get deployments,replicasets,pods,services,ingress,certificates -o wide
kubectl -n tokenplace describe deploy/tokenplace
kubectl -n tokenplace describe ingress/tokenplace
kubectl -n tokenplace get events --sort-by=.lastTimestamp | tail -n 80
kubectl -n tokenplace logs deploy/tokenplace --since=30m --tail=500
kubectl -n tokenplace logs deploy/tokenplace --previous --tail=500 || true
curl -vI "https://${TOKENPLACE_HOST}/"
curl -fsS "https://${TOKENPLACE_HOST}/healthz" || true
curl -fsS "https://${TOKENPLACE_HOST}/relay/diagnostics" || true
just cf-tunnel-debug
just cert-manager-status
```

If Cloudflare returns HTTP 403 before the request reaches the app, check Cloudflare Security
Events for the exact hostname, ray ID, source IP, path, and rule that blocked the request.

## Rollback

Rollback reminders:

- Prefer immutable image tag rollback when the bad rollout is tied to a single image.
- Use Helm revision rollback when you need to restore the entire rendered release state.
- Expect a short outage during rollback because token.place is intentionally single-replica and
  the Deployment strategy is `Recreate`; wait for the replacement pod before retesting relay E2EE.

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