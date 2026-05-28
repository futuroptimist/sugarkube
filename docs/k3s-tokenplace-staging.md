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
curl -fsS https://staging.token.place/relay/diagnostics | jq .
```

### Staging validation sequence

Run the checks in this order after each staging candidate rollout. During the incident that prompted
this runbook update, basic web/TLS checks and synthetic register/poll both passed, but a public
`/healthz` watch plus Kubernetes probes exposed that `/healthz` was still covered by the public API
rate limit and could make readiness look broken. Treat high-frequency public health checks as a
load/rate-limit test, not as the primary readiness monitor, until the relay release under test is
known to exempt `/livez`, `/healthz`, metrics, diagnostics, and API v1 compute-node heartbeat routes
from global API rate limits.

1. **Web/TLS smoke:** confirm Cloudflare, tunnel routing, Traefik, ingress, and certificate wiring.

   ```bash
   curl -vI https://staging.token.place/
   curl -fsS https://staging.token.place/
   ```

2. **Low-frequency public health/diagnostics:** call each endpoint once or on a slow cadence. Do not
   run a tight `watch curl https://staging.token.place/healthz` loop as the readiness source of truth.

   ```bash
   curl -fsS https://staging.token.place/livez
   curl -fsS https://staging.token.place/healthz | jq .
   curl -fsS https://staging.token.place/relay/diagnostics | jq .
   ```

3. **Readiness without abusing public health endpoints:** use Kubernetes state and relay logs first,
   then use public diagnostics sparingly.

   ```bash
   kubectl -n tokenplace get endpoints
   kubectl -n tokenplace get deploy,po
   kubectl -n tokenplace logs deploy/tokenplace --tail=200
   curl -fsS https://staging.token.place/relay/diagnostics | jq .
   ```

4. **Synthetic API v1 compute-node register/poll:** register a throwaway debug server and then poll
   with a bounded long-poll timeout. The debug server is in relay memory only and will age out by its
   normal lease/TTL; do not use production secrets or a real operator key for this synthetic check.

   ```bash
   DEBUG_KEY="debug-$(date -u +%Y%m%dT%H%M%SZ)-$(openssl rand -hex 6)"
   DEBUG_SERVER_ID="sugarkube-staging-${DEBUG_KEY}"

   curl -fsS -X POST https://staging.token.place/api/v1/compute/servers/register \
     -H 'content-type: application/json' \
     --data @- <<EOF | jq .
   {
     "serverId": "${DEBUG_SERVER_ID}",
     "debugKey": "${DEBUG_KEY}",
     "models": ["debug/sugarkube-smoke"],
     "capacity": 1,
     "metadata": {
       "source": "sugarkube-staging-runbook",
       "environment": "staging"
     }
   }
   EOF

   curl -fsS https://staging.token.place/healthz | jq '.knownServers // .servers // .'

   curl -fsS --max-time 20 -X POST https://staging.token.place/api/v1/compute/servers/poll \
     -H 'content-type: application/json' \
     --data @- <<EOF | jq .
   {
     "serverId": "${DEBUG_SERVER_ID}",
     "debugKey": "${DEBUG_KEY}"
   }
   EOF
   ```

   If token.place changes the exact debug payload schema, keep the same validation intent: generate a
   unique `DEBUG_KEY`, register a synthetic server through the API v1 registration route, confirm
   `knownServers`/server visibility through health or diagnostics, and poll
   `/api/v1/compute/servers/poll` with `--max-time 20`.

5. **Desktop compute-node registration:** start the desktop/Tauri compute-node client against
   `https://staging.token.place`, confirm the desktop reports registered, and confirm relay logs show
   matching API v1 register/poll `POST` requests.

   ```bash
   kubectl -n tokenplace logs deploy/tokenplace --tail=200 | grep -E 'POST .*/api/v1/.*/(register|poll)'
   curl -fsS https://staging.token.place/relay/diagnostics | jq '.knownServers // .servers // .'
   ```

6. **End-to-end encrypted request/response:** before production promotion, send a real desktop or
   external compute-node E2EE request through staging and verify the encrypted response returns to the
   requesting client. Synthetic register/poll proves the relay API path works; production signoff
   additionally requires an external compute-node registration plus a successful E2EE request/response.

### Desktop HTTP 403 / pre-app rejection triage

During staging, the desktop client saw HTTP 403 while synthetic `curl` register/poll succeeded, and
relay logs did not contain corresponding desktop register/poll `POST` lines. That combination means
Cloudflare or another pre-app layer likely rejected the request before it reached the relay. Triage in
this order:

1. Capture the desktop response headers and note the `cf-ray` value, timestamp, method, URL, and
   source IP/network.
2. Check relay logs for a matching `POST`. If the relay log entry is absent, debug Cloudflare before
   changing the app.

   ```bash
   kubectl -n tokenplace logs deploy/tokenplace --since=30m | grep -E 'POST .*/api/v1/.*/(register|poll)'
   ```

3. Use the `cf-ray` value in **Cloudflare Security Events** for the `token.place` zone to identify the
   blocking product/rule: WAF, bot management, security level, access policy, rate limit, or custom
   rule.
4. Compare a passing synthetic request with the failing desktop request: method, path, `Host`,
   `User-Agent`, `Origin`, `Referer`, `Content-Type`, `Accept`, auth/debug headers, request body
   shape, and whether the desktop performs an `OPTIONS` preflight.
5. Confirm tunnel and DNS credentials are not mixed up. `CF_TUNNEL_TOKEN` is the token-only
   Cloudflare Tunnel connector credential; cert-manager DNS-01 uses a separate Cloudflare DNS API
   token. Neither token should be pasted into desktop settings or committed to Sugarkube docs.
6. Once Cloudflare allows the desktop request, rerun the desktop registration and confirm relay logs
   now show register/poll `POST` entries plus a successful E2EE request/response.

## Rollback

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

If cert-manager logs cleanup errors after issuance, gate release on the Kubernetes Certificate state,
not on noisy solver cleanup alone: `Ready=True` on the target Certificate means the usable TLS Secret
was issued. Cleanup failures still deserve follow-up because they can indicate the DNS API token lacks
`Zone -> Zone -> Read`, the token is scoped to the wrong zone, or Cloudflare zone/resolver lookup is
behaving unexpectedly.

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
