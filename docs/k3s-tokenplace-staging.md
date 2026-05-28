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
curl -fsS https://staging.token.place/relay/diagnostics
```

### Staging signoff sequence

Run these checks in order after every staging deploy. Basic web/TLS checks are necessary but not
sufficient; real production signoff requires an external compute node to register through the
desktop/server client and complete an end-to-end encrypted (E2EE) request/response through the
relay.

1. **Web/TLS smoke tests:**

   ```bash
   curl -vI https://staging.token.place/
   curl -fsS https://staging.token.place/livez
   curl -fsS https://staging.token.place/healthz
   curl -fsS https://staging.token.place/relay/diagnostics
   ```

2. **Inspect readiness without hammering public health endpoints:**

   ```bash
   kubectl -n tokenplace get endpoints
   kubectl -n tokenplace get deploy,po
   kubectl -n tokenplace logs deploy/tokenplace --tail=200
   curl -fsS https://staging.token.place/relay/diagnostics
   ```

   Avoid long-running public `/healthz` watches such as `watch curl .../healthz` as a primary
   readiness monitor until `/healthz`, `/livez`, metrics, diagnostics, and API v1 relay heartbeat
   routes are confirmed exempt from global API rate limits. During staging, a public `/healthz` watch
   combined with Kubernetes probes consumed rate-limit budget, caused `429` responses, and made
   readiness appear unstable even though web/TLS and synthetic API v1 checks were otherwise healthy.

3. **Synthetic API v1 compute-node registration:**

   ```bash
   DEBUG_KEY="debug-$(date -u +%Y%m%dT%H%M%SZ)-$(openssl rand -hex 8)"
   export DEBUG_KEY

   curl -fsS -X POST https://staging.token.place/api/v1/servers/register \
     -H 'content-type: application/json' \
     --data "{\"serverId\":\"$DEBUG_KEY\",\"publicKey\":\"$DEBUG_KEY\",\"url\":\"debug://$DEBUG_KEY\",\"capacity\":1}"
   ```

   The debug server is intentionally synthetic and will age out by the relay lease/TTL. Do not reuse
   the generated `DEBUG_KEY` as a credential.

4. **Confirm registration appears in health output, then poll with a bounded wait:**

   ```bash
   curl -fsS https://staging.token.place/healthz | jq --arg key "$DEBUG_KEY" '.knownServers? // .servers? // . | tostring | contains($key)'

   curl -fsS --max-time 20 -X POST https://staging.token.place/api/v1/servers/poll \
     -H 'content-type: application/json' \
     --data "{\"serverId\":\"$DEBUG_KEY\"}"
   ```

   A successful empty/no-work poll still validates that the API v1 registration/poll route reaches
   the relay. Keep `--max-time 20` so a quiet queue cannot hang the runbook.

5. **Desktop compute-node registration:** point the desktop client at
   `https://staging.token.place`, verify its staging `knownServers`/relay configuration is not using
   a production URL, and confirm relay logs show the corresponding API v1 `register` or
   `servers/poll` POST.

6. **E2EE request/response:** submit a real client request to the externally registered compute
   node and verify the encrypted response returns through staging. The relay must remain blind to
   plaintext; use only safe routing metadata and ciphertext-level diagnostics in logs.

### Desktop HTTP 403 / pre-app rejection triage

If the desktop client reports HTTP 403 while synthetic `curl` registration/poll succeeds, determine
whether the request reached the relay before changing application code:

1. Check relay logs for matching desktop POSTs around the failure time:

   ```bash
   kubectl -n tokenplace logs deploy/tokenplace --since=15m | grep -E 'api/v1|register|servers/poll|403|cf-ray'
   ```

2. If no matching POST appears, treat the 403 as a pre-app rejection. Capture the `cf-ray` response
   header from the desktop failure, then inspect **Cloudflare Security Events** for that Ray ID, the
   client IP, and the user agent.
3. Compare a successful synthetic curl request and the desktop request headers: method, path
   (`/api/v1/servers/register` or `/api/v1/servers/poll`), `Host`, `Origin`, `User-Agent`,
   `Content-Type`, auth/debug headers, and any Cloudflare Access or WAF-triggering headers.
4. Confirm Cloudflare Tunnel credentials are not being confused with DNS credentials.
   `CF_TUNNEL_TOKEN` is the connector token for the tunnel route; `CF_DNS_API_TOKEN` is the separate
   Cloudflare DNS API token used by cert-manager DNS-01. Neither token belongs in desktop client
   configuration or logs.

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

Validation commands:

```bash
kubectl get crd | grep cert-manager.io
kubectl get clusterissuer letsencrypt-staging letsencrypt-production
kubectl get certificate --all-namespaces
kubectl -n cert-manager get secret cloudflare-api-token
kubectl -n cert-manager logs deploy/cert-manager --tail=100
```

For release gating, require the relevant `Certificate` to report `Ready=True`:

```bash
kubectl -n tokenplace get certificate
kubectl -n tokenplace describe certificate tokenplace-staging-tls
```

cert-manager may log DNS-01 challenge cleanup errors after successful issuance. Treat
`Certificate Ready=True` and a valid served certificate as the staging release gate, but investigate
cleanup errors before production promotion: they can indicate the Cloudflare DNS API token is missing
`Zone -> Zone -> Read`, the token is scoped to the wrong zone, or cert-manager/Cloudflare had a
resolver or zone-lookup mismatch while deleting the temporary `_acme-challenge` record.

> ⚠️ During early staging we used manual Helm `--set env.XDG_CACHE_HOME=/tmp --set env.XDG_CONFIG_HOME=/tmp --set env.XDG_DATA_HOME=/tmp` overrides to pass read-only filesystem startup checks. Remove those manual overrides now that chart defaults own the XDG `/tmp` paths.


## 0.1.0 release alignment

- OCI chart package version: `0.1.0`
- Chart `appVersion`: `0.1.0`
- token.place Git tag: `v0.1.0`
- Release image tag after final tag push: `ghcr.io/futuroptimist/tokenplace-relay:v0.1.0`
- Staging candidate tag before final tag push: `main-<shortsha>`
