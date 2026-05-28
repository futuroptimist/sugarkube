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

### Staging sign-off sequence

Run the checks in this order so each layer has a clear owner before moving on to real
external compute-node traffic:

1. **Web/TLS:** confirm Cloudflare, Traefik, Ingress, and cert-manager serve the staging host.
2. **Liveness/readiness:** call `/livez`, `/healthz`, and `/relay/diagnostics` once or at low
   frequency. Do **not** use a long-running public `/healthz` watch as the primary readiness
   monitor until token.place confirms health, liveness, metrics, diagnostics, and API v1
   compute-node heartbeat routes are exempt from global public API rate limits. In staging, a
   public `/healthz` watch plus kube-probes showed that rate-limited health checks can distort
   readiness and create false rollout failures.
3. **Synthetic API v1 register:** register a throwaway compute-node key against
   `/api/v1/relay/servers/register`.
4. **Synthetic API v1 poll:** poll `/api/v1/relay/servers/poll` with a client timeout that
   exceeds the relay's server-side long-poll hold plus a small buffer, verifying the path returns
   either queued encrypted work or a healthy no-work response instead of a client-side timeout.
5. **Desktop compute-node registration:** start the packaged desktop/compute node against
   `https://staging.token.place` and confirm the relay logs show matching API v1 register/poll
   POSTs for that node.
6. **E2EE request/response:** submit a real encrypted request through the staging client and verify
   an encrypted response round trip. Synthetic register/poll is necessary, but real production
   signoff requires an external compute-node registration and an E2EE request/response.

Use Kubernetes state and relay logs for readiness instead of hammering public health endpoints:

```bash
kubectl -n tokenplace get endpoints
kubectl -n tokenplace get deploy,po
kubectl -n tokenplace logs deploy/tokenplace --since=15m --tail=200
curl -fsS https://staging.token.place/relay/diagnostics
```

Keep the public diagnostics curl low-frequency (for example, one manual call during validation or
one scheduled check every few minutes) so the check itself does not trip public API rate-limit traps.

### Synthetic API v1 compute-node register/poll

This synthetic test proves the relay can accept an API v1 compute-node heartbeat without requiring
a desktop package or GPU host. It does not prove desktop packaging, request routing, or E2EE.

```bash
BASE_URL=https://staging.token.place
KEY_DIR="$(mktemp -d)"
trap 'rm -rf "${KEY_DIR}"' EXIT

# Generate real public-key material for the synthetic compute node instead of a debug string.
# If the desktop client emits a different accepted format, set SYNTHETIC_SERVER_PUBLIC_KEY
# to a non-secret public key copied from a disposable desktop test node.
openssl genpkey -algorithm Ed25519 -out "${KEY_DIR}/server.key" >/dev/null 2>&1
openssl pkey -in "${KEY_DIR}/server.key" -pubout -out "${KEY_DIR}/server.pub" >/dev/null 2>&1
SERVER_PUBLIC_KEY="${SYNTHETIC_SERVER_PUBLIC_KEY:-$(cat "${KEY_DIR}/server.pub")}"
REGISTER_BODY="$(jq -n --arg server_public_key "${SERVER_PUBLIC_KEY}" \
  '{server_public_key: $server_public_key}')"

# If the relay requires compute-node registration auth, populate RELAY_SERVER_CREDENTIAL
# from your secret manager before running this block. Do not paste real secrets
# into shell history, docs, screenshots, or PRs.

RELAY_AUTH_HEADER_NAME="X-Relay-Server-Token"
AUTH_HEADER=()
if [ -n "${RELAY_SERVER_CREDENTIAL:-}" ]; then
  AUTH_HEADER=(-H "${RELAY_AUTH_HEADER_NAME}: ${RELAY_SERVER_CREDENTIAL}")
fi

curl -fsS -X POST "${BASE_URL}/api/v1/relay/servers/register" \
  -H 'Content-Type: application/json' \
  "${AUTH_HEADER[@]}" \
  --data "${REGISTER_BODY}" | jq .

curl -fsS "${BASE_URL}/healthz" | jq '{status, knownServers, registeredServers}'

# Keep this higher than the relay's server-side long-poll hold. The default 65s value
# leaves buffer for relays that hold empty polls for up to one minute before returning
# the healthy no-work response; raise it if staging is configured with a longer hold.
POLL_MAX_TIME="${POLL_MAX_TIME:-65}"
curl -fsS --max-time "${POLL_MAX_TIME}" -X POST "${BASE_URL}/api/v1/relay/servers/poll" \
  -H 'Content-Type: application/json' \
  "${AUTH_HEADER[@]}" \
  --data "${REGISTER_BODY}" | jq .
```

Expected result: register returns wait hints, `/healthz` reports `knownServers` increased while the
lease is fresh, and poll returns either encrypted work or a `No requests available` response before
`POLL_MAX_TIME` elapses. The synthetic server is ephemeral and will age out automatically after the
relay lease if it is not refreshed.

### Desktop HTTP 403 / pre-app rejection triage

If the desktop compute-node reports HTTP 403 but synthetic curl succeeds, determine whether the
request reached Flask/Gunicorn or was rejected before the app:

1. Capture the desktop failure timestamp, request path, response status, and Cloudflare `cf-ray`
   header from the desktop diagnostics or HTTP trace.
2. Check relay logs for matching API v1 POSTs around that timestamp:

   ```bash
   kubectl -n tokenplace logs deploy/tokenplace --since=30m --tail=500 | \
     grep -E 'api/v1/relay/servers/(register|poll)|server\.(registered|reregister|heartbeat)'
   ```

3. If there is no corresponding relay log entry, treat it as a Cloudflare/pre-app rejection and
   search **Cloudflare Security Events** for the `cf-ray` value, client IP, host, path, and user
   agent.
4. Compare synthetic curl and desktop request headers: method, host, path, `Content-Type`,
   `User-Agent`, `Origin`, any desktop-specific headers, and whether `X-Relay-Server-Token` is
   present when required.
5. Confirm credentials are not mixed up: `CF_TUNNEL_TOKEN` connects the Cloudflare Tunnel connector
   to the dashboard tunnel, while the Cloudflare DNS API token is only for cert-manager DNS-01.
   Neither token should be sent as the API v1 relay server registration token.

A 403 with no relay log line means the application probably never saw the POST. A 403 with a relay
log line means inspect token.place auth/rate-limit handling and the exact response body.

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

If cert-manager logs show challenge cleanup errors after a certificate is already issued, use the
Certificate condition as the release gate: `Ready=True` means TLS issuance succeeded for rollout
purposes. Cleanup errors are still worth fixing because they usually point to a Cloudflare DNS API
token without `Zone -> Zone -> Read`, a token scoped to the wrong zone, or resolver/zone lookup
weirdness that prevents cert-manager from finding the correct Cloudflare zone during cleanup.

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
