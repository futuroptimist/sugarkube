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
kubectl -n tokenplace get endpoints
kubectl -n tokenplace get ingress tokenplace -o yaml
kubectl -n tokenplace logs deploy/tokenplace --tail=100
curl -vI https://staging.token.place/
curl -fsS https://staging.token.place/livez
curl -fsS https://staging.token.place/healthz
curl -fsS https://staging.token.place/relay/diagnostics | jq .
```

### Staging validation sequence

Run validation in this order so the release notes can distinguish basic ingress/TLS health from
relay-specific API v1 readiness:

1. **Web/TLS smoke:** confirm Cloudflare Tunnel, Traefik, Ingress, and TLS all route to staging.

   ```bash
   curl -vI https://staging.token.place/
   ```

2. **Low-frequency liveness/health/diagnostics:** call probe endpoints once per validation pass, not
   as a tight public watch.

   ```bash
   curl -fsS https://staging.token.place/livez
   curl -fsS https://staging.token.place/healthz | jq .
   curl -fsS https://staging.token.place/relay/diagnostics | jq .
   ```

   Avoid long-running public `/healthz` watches as the primary readiness monitor until `/livez`,
   `/healthz`, `/metrics`, `/relay/diagnostics`, and API v1 relay heartbeat routes are confirmed
   exempt from global public API rate limits. During staging, a public `/healthz` watch combined with
   Kubernetes probes made `/healthz` return rate-limit responses and distorted readiness. Prefer the
   cluster-local checks below when you need continuous status:

   ```bash
   kubectl -n tokenplace get endpoints
   kubectl -n tokenplace get deploy,po
   kubectl -n tokenplace logs deploy/tokenplace --tail=100 -f
   # Optional, low-frequency external diagnostic sample:
   curl -fsS https://staging.token.place/relay/diagnostics | jq .
   ```

3. **Synthetic API v1 compute-node register:** create an ephemeral debug public key and register it.
   This validates the API v1 registration route without requiring a desktop or server-side secret.

   ```bash
   DEBUG_KEY="debug-$(date -u +%Y%m%dT%H%M%SZ)-$(openssl rand -hex 8)"
   curl -fsS -X POST https://staging.token.place/api/v1/relay/servers/register \
     -H 'Content-Type: application/json' \
     --data "$(jq -nc --arg key "$DEBUG_KEY" '{server_public_key:$key}')" | jq .
   ```

4. **Confirm the synthetic node is visible:** `/healthz` reports `knownServers` and
   `registeredServers`, and `/relay/diagnostics` reports `registered_compute_nodes`. Keep this a
   one-shot check so validation does not become a health-endpoint load test.

   ```bash
   curl -fsS https://staging.token.place/healthz | jq '.knownServers, .registeredServers'
   curl -fsS https://staging.token.place/relay/diagnostics | jq '.total_registered_compute_nodes, .registered_compute_nodes'
   ```

5. **Synthetic API v1 poll:** long-poll once with a finite client timeout. `--max-time 20` is
   deliberate: an idle relay may wait for work before returning `No requests available`.

   ```bash
   curl -fsS --max-time 20 -X POST https://staging.token.place/api/v1/relay/servers/poll \
     -H 'Content-Type: application/json' \
     --data "$(jq -nc --arg key "$DEBUG_KEY" '{server_public_key:$key}')" | jq .
   ```

   The synthetic debug server is only an in-memory registration and will age out by lease; do not
   depend on it for later validation.

6. **Desktop compute-node registration:** start the desktop compute node against
   `https://staging.token.place` and confirm relay logs include matching
   `POST /api/v1/relay/servers/register` followed by `POST /api/v1/relay/servers/poll`. The desktop
   relay-client diagnostics should show the staging URL in its configured targets/`knownServers`
   path, not a production URL.

   ```bash
   kubectl -n tokenplace logs deploy/tokenplace --since=10m | \
     rg 'api/v1/relay/servers/(register|poll)|server\.(registered|reregister|heartbeat)|http.request'
   ```

7. **E2EE request/response:** send a real encrypted client request through the registered external
   compute node and verify the encrypted response can be retrieved and decrypted by the client.
   Health/root checks and synthetic register/poll prove routing and relay state only; real production
   signoff requires external compute-node registration plus an end-to-end encrypted
   request/response.

### Desktop HTTP 403 / pre-app rejection triage

If the desktop reports HTTP 403 but synthetic `curl` register/poll succeeds, determine whether the
request reached Flask before debugging relay code:

1. Capture the desktop response headers, especially `cf-ray`, status, path, method, and User-Agent.
2. Check relay logs for a matching POST and Cloudflare Ray ID:

   ```bash
   kubectl -n tokenplace logs deploy/tokenplace --since=15m | \
     rg 'cf-ray|api/v1/relay/servers/(register|poll)|HTTP 403|http.request|server\.(registered|heartbeat)'
   ```

3. If there is no matching POST in relay logs, treat it as pre-app rejection and inspect
   **Cloudflare Security Events** for the captured `cf-ray`. Check WAF, Bot Fight Mode, Access,
   transform rules, and any managed challenge or block action on `staging.token.place`.
4. Compare synthetic curl and desktop request headers: method, URL, `Host`, `Content-Type`,
   `User-Agent`, `Accept`, `Authorization`, Origin/Referer, and any desktop proxy/VPN headers. Use a
   synthetic request with a desktop-like User-Agent to reproduce Cloudflare decisions without sending
   secrets:

   ```bash
   curl -v --max-time 20 -X POST https://staging.token.place/api/v1/relay/servers/register \
     -H 'Content-Type: application/json' \
     -H 'User-Agent: token.place-desktop-debug' \
     --data "$(jq -nc --arg key "debug-desktop-headers-$(openssl rand -hex 8)" '{server_public_key:$key}')"
   ```

5. Keep Cloudflare credentials separate: `CF_TUNNEL_TOKEN` is the connector token used by
   `cloudflared`; it is not the Cloudflare DNS API token used by cert-manager DNS-01 and cannot fix
   WAF/Security Events or DNS challenge permissions.

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

For release gating, `Ready=True` on the relevant `Certificate` is the cert-manager success signal:

```bash
kubectl -n tokenplace get certificate tokenplace-staging-tls -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}{"\n"}'
```

Post-issuance DNS-01 cleanup errors can appear after the certificate is already issued. Treat those
as follow-up hygiene unless `Certificate` readiness regresses. Cleanup failures commonly mean the
Cloudflare DNS API token is missing `Zone -> Zone -> Read`, the token is scoped to the wrong zone,
or cert-manager is doing an unexpected resolver/zone lookup; they are separate from Cloudflare
Tunnel token problems.

> ⚠️ During early staging we used manual Helm `--set env.XDG_CACHE_HOME=/tmp --set env.XDG_CONFIG_HOME=/tmp --set env.XDG_DATA_HOME=/tmp` overrides to pass read-only filesystem startup checks. Remove those manual overrides now that chart defaults own the XDG `/tmp` paths.


## 0.1.0 release alignment

- OCI chart package version: `0.1.0`
- Chart `appVersion`: `0.1.0`
- token.place Git tag: `v0.1.0`
- Release image tag after final tag push: `ghcr.io/futuroptimist/tokenplace-relay:v0.1.0`
- Staging candidate tag before final tag push: `main-<shortsha>`
