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

Treat these checks as release blockers before any staging candidate can be promoted to production.
Passing web, TLS, `/livez`, `/healthz`, `/`, `/metrics`, or synthetic register/poll probes alone
does **not** validate the relay release; the actual desktop compute path must pass too.

- [ ] **OCI chart freshness:** `helm show chart` and the captured chart digest match the current
  token.place release candidate, not an earlier `0.1.0` publish.
- [ ] **No duplicate env vars:** the render validation above exits cleanly with no duplicate env names.
- [ ] **XDG env present:** rendered Deployment env includes chart-owned XDG `/tmp` paths without
  one-off manual Helm overrides.
- [ ] **`/healthz` exempt from rate limit:** repeated unauthenticated health probes return success
  and do not consume or trip the global API rate limit.
- [ ] **Synthetic register/poll passes:** the API v1 synthetic compute-node register/poll smoke test
  succeeds against `https://staging.token.place`.
- [ ] **Desktop compute node registers:** a real desktop compute node whose `knownServers` targets
  staging successfully registers through the public relay path.
- [ ] **Registered compute node is visible:** the node appears in both `/healthz` and
  `/relay/diagnostics` after registration.
- [ ] **E2EE request/response passes:** an end-to-end encrypted request submitted through staging is
  accepted by the registered compute node and returns an encrypted response to the requester.
- [ ] **Production Cloudflare route is ready before promotion:** `token.place` is explicitly routed
  to Traefik with `just cf-tunnel-route host=token.place` before the production upgrade window.

## Release evidence capture

Capture these artifacts in the staging sign-off notes so reviewers can distinguish web health from
relay-path validation:

```bash
CHART_VERSION="$(grep -E '^[0-9]+\.[0-9]+\.[0-9]+' docs/apps/tokenplace.version | head -n1)"
TOKENPLACE_TAG=main-deadbee # replace with the immutable candidate tag
helm show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version "$CHART_VERSION"
helm pull oci://ghcr.io/futuroptimist/charts/tokenplace --version "$CHART_VERSION" \
  --destination /tmp/tokenplace-chart-evidence
sha256sum /tmp/tokenplace-chart-evidence/tokenplace-"$CHART_VERSION".tgz # chart digest
printf 'image tag: ghcr.io/futuroptimist/tokenplace-relay:%s\n' "$TOKENPLACE_TAG"
kubectl -n tokenplace get deploy tokenplace -o yaml > /tmp/tokenplace-staging-deployment.yaml
curl -fsS https://staging.token.place/healthz | tee /tmp/tokenplace-staging-healthz.json
curl -fsS https://staging.token.place/relay/diagnostics | tee /tmp/tokenplace-staging-diagnostics.json
# Run the desktop compute-node registration and E2EE request/response test now.
kubectl -n tokenplace logs deploy/tokenplace --tail=200 > /tmp/tokenplace-staging-relay-after-compute.log
```

## Emergency diagnostics

Copy/paste this block when staging web health passes but compute-node registration, diagnostics, or
E2EE relay traffic fails:

```bash
just kubeconfig-env staging
kubectl -n tokenplace get deployments,replicasets,pods,services,ingress,certificates -o wide
kubectl -n tokenplace describe deploy tokenplace
kubectl -n tokenplace describe ingress tokenplace
kubectl -n tokenplace get events --sort-by=.lastTimestamp | tail -n 80
kubectl -n tokenplace logs deploy/tokenplace --tail=300
kubectl -n tokenplace logs deploy/tokenplace --previous --tail=300 || true
just tokenplace-debug-logs-env env=staging
just cf-tunnel-debug
just cert-manager-status
```

Also check Cloudflare Security Events for `staging.token.place` and `token.place` around the failed
registration time. A Cloudflare WAF/rate-limit/challenge event can reject requests before the relay
application logs anything.

## Rollback

Rollback by immutable image tag when the prior good container image is known:

```bash
just kubeconfig-env staging
TOKENPLACE_PREVIOUS_TAG=main-deadbee # replace with the prior immutable tag
just helm-oci-upgrade release=tokenplace namespace=tokenplace chart=oci://ghcr.io/futuroptimist/charts/tokenplace values=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.staging.yaml version_file=docs/apps/tokenplace.version default_tag="$TOKENPLACE_PREVIOUS_TAG"
```

Rollback by Helm revision when the prior good release revision is known:

```bash
just kubeconfig-env staging
TOKENPLACE_REVISION=12 # replace with the known-good Helm revision
just tokenplace-rollback release=tokenplace namespace=tokenplace revision="$TOKENPLACE_REVISION"
```

Both rollback paths restart the only relay pod because the Deployment strategy is `Recreate`. Expect
a short downtime window and loss of in-memory relay registrations while the single replacement pod
starts.

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
