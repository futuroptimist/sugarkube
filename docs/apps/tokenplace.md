# token.place on Sugarkube

This is the canonical runbook for deploying token.place from GHCR artifacts to Sugarkube. The generic `just app-*` recipes are the preferred future path. The `tokenplace-oci-*` recipes remain compatibility shims and are scheduled for later removal only after the generic flow has been exercised across routine releases.

## Artifact model

- App repository responsibilities: build `ghcr.io/futuroptimist/tokenplace-relay`, publish immutable image tags, maintain the Helm chart, and publish immutable chart versions to `oci://ghcr.io/futuroptimist/charts/tokenplace`.
- Sugarkube responsibilities: select `dev`, `staging`, or `prod`; load `docs/examples/apps/tokenplace.env` or a local override; select kubeconfig/context; install or upgrade Helm; verify rollout status, logs, and public paths.
- Cloudflare responsibilities: DNS and Tunnel routes to Traefik are outside Helm and must exist before public verification.

| Coordinate | Value |
| --- | --- |
| Image | `ghcr.io/futuroptimist/tokenplace-relay` |
| Chart | `oci://ghcr.io/futuroptimist/charts/tokenplace` |
| Release | `tokenplace` |
| Namespace | `tokenplace` |
| App config | `docs/examples/apps/tokenplace.env` |
| Chart version pin | `docs/apps/tokenplace.version` |
| Production tag pin | `docs/apps/tokenplace.prod.tag` |
| Verify paths | `/`, `/livez`, `/healthz`, `/relay/diagnostics` |

## Environment topology

- `env=dev`: local/dev defaults using `docs/examples/tokenplace.values.dev.yaml`.
- `env=staging`: staging host `staging.token.place` with values `docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.staging.yaml`.
- `env=prod`: production host `token.place` with values `docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.prod.yaml`.
- token.place may depend on external compute-node or upstream runtime configuration; keep secrets and per-environment runtime config out of Sugarkube docs and app config files.

## Find or publish GHCR image

Find the successful image workflow in the token.place app repo and copy the immutable branch-SHA or release tag. Do not deploy `latest`, a bare branch name, or an environment name.

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
gh run list --repo futuroptimist/token.place --workflow ci-image.yml --branch main --status success --limit 5
```

If no suitable image exists, publish it from the app repo workflow, then return here with the immutable tag it produced.

```bash
gh workflow run ci-image.yml --repo futuroptimist/token.place --ref main
```

## Confirm/publish OCI chart

Sugarkube deploys the chart version pinned in `docs/apps/tokenplace.version`.

```bash
CHART_VERSION=$(sed -e 's/#.*$//' -e '/^[[:space:]]*$/d' docs/apps/tokenplace.version | head -n 1)
```

```bash
helm show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version "$CHART_VERSION"
```

If the chart changed, bump the chart version in the token.place app repo and publish it there with `ci-helm.yml`; do not republish a different chart under an existing OCI version.

```bash
gh workflow run ci-helm.yml --repo futuroptimist/token.place --ref main
```

## Deploy staging

Preferred generic command:

```bash
just app-deploy app=tokenplace env=staging tag="$APP_TAG"
```

Compatibility shim while migration is in progress:

```bash
just tokenplace-oci-deploy env=staging tag="$APP_TAG"
```

## Verify staging

```bash
just app-status app=tokenplace env=staging
```

```bash
just app-verify app=tokenplace env=staging
```

```bash
curl -fsS https://staging.token.place/healthz
```

```bash
curl -fsS https://staging.token.place/livez
```

```bash
curl -fsS https://staging.token.place/relay/diagnostics | jq .
```

### Staging relay-compute sign-off

`app-status`, `app-verify`, health, liveness, and `/relay/diagnostics` are necessary but not sufficient for token.place promotion. Before production promotion, capture staging evidence for the real relay path:

- [ ] Synthetic API v1 compute-node registration succeeds against `https://staging.token.place/api/v1/relay/servers/register`.
- [ ] Synthetic API v1 compute-node polling succeeds against `https://staging.token.place/api/v1/relay/servers/poll` without a client-side timeout.
- [ ] A real desktop or compute node is configured for `staging.token.place`, registers to staging, and appears in `/healthz` and `/relay/diagnostics`.
- [ ] A real E2EE request/response succeeds through that staging compute node.

Use this copy-pasteable synthetic register/poll block as the minimum API proof before the real desktop or compute-node E2EE test. Populate `RELAY_SERVER_CREDENTIAL` from a secret manager only when the relay requires registration auth; never paste secret values into docs, shell history, screenshots, or PRs.

```bash
BASE_URL=https://staging.token.place
KEY_DIR="$(mktemp -d)"
trap 'rm -rf "${KEY_DIR}"' EXIT
openssl genpkey -algorithm Ed25519 -out "${KEY_DIR}/server.key" >/dev/null 2>&1
openssl pkey -in "${KEY_DIR}/server.key" -pubout -out "${KEY_DIR}/server.pub" >/dev/null 2>&1
SERVER_PUBLIC_KEY="${SYNTHETIC_SERVER_PUBLIC_KEY:-$(cat "${KEY_DIR}/server.pub")}"
REGISTER_BODY="$(jq -n --arg server_public_key "${SERVER_PUBLIC_KEY}" \
  '{server_public_key: $server_public_key}')"
AUTH_HEADER=()
if [ -n "${RELAY_SERVER_CREDENTIAL:-}" ]; then
  AUTH_HEADER=(-H "X-Relay-Server-To""ken"": ${RELAY_SERVER_CREDENTIAL}")
fi

curl -fsS -X POST "${BASE_URL}/api/v1/relay/servers/register" \
  -H 'Content-Type: application/json' \
  "${AUTH_HEADER[@]}" \
  --data "${REGISTER_BODY}" | jq .

curl -fsS "${BASE_URL}/relay/diagnostics" | jq -e --arg key "${SERVER_PUBLIC_KEY}" \
  '(.registered_compute_nodes // []) | any(.server_public_key == $key)'

POLL_MAX_TIME="${POLL_MAX_TIME:-65}"
curl -fsS --max-time "${POLL_MAX_TIME}" -X POST "${BASE_URL}/api/v1/relay/servers/poll" \
  -H 'Content-Type: application/json' \
  "${AUTH_HEADER[@]}" \
  --data "${REGISTER_BODY}" | jq .
```

Expected result: register returns relay wait hints, diagnostics includes the fresh synthetic `server_public_key`, and poll returns either encrypted work or a healthy no-work response before `POLL_MAX_TIME` elapses.

## Promote production

Promote only after staging sign-off, including synthetic API v1 register/poll, real desktop or compute-node registration, and a real E2EE request/response through staging. Prefer the generic command; it uses the prod values chain and can read `docs/apps/tokenplace.prod.tag` when `tag=` is omitted.

```bash
just app-promote-prod app=tokenplace tag="$APP_TAG"
```

Compatibility shim:

```bash
just tokenplace-oci-promote-prod tag="$APP_TAG"
```

## Verify production

```bash
just app-status app=tokenplace env=prod
```

```bash
just app-verify app=tokenplace env=prod
```

```bash
curl -fsS https://token.place/healthz
```

```bash
curl -fsS https://token.place/livez
```

```bash
curl -fsS https://token.place/relay/diagnostics | jq .
```

### Production relay-compute proof

Do not mark production healthy on generic HTTP checks alone. After promotion, prove the production relay path separately from staging:

- [ ] Synthetic API v1 compute-node registration and polling pass against `https://token.place`.
- [ ] A real desktop or compute node is configured for `token.place`, registers to production, and does not silently fall back to staging.
- [ ] The production-registered compute node appears in production `/healthz` and `/relay/diagnostics`.
- [ ] A real E2EE request/response succeeds through the production-registered compute node.
- [ ] Evidence is captured after the production E2EE test so health, diagnostics, and logs prove the real prod relay-compute path passed.

```bash
TOKENPLACE_HOST=token.place
kubectl -n tokenplace get deploy tokenplace -o yaml > /tmp/tokenplace-prod-deployment.yaml
# First run synthetic register/poll, production desktop compute-node registration,
# and the production E2EE request/response. Then capture post-test evidence:
curl -fsS "https://${TOKENPLACE_HOST}/healthz" | tee /tmp/tokenplace-prod-healthz.json
curl -fsS "https://${TOKENPLACE_HOST}/relay/diagnostics" | tee /tmp/tokenplace-prod-diagnostics.json
kubectl -n tokenplace logs deploy/tokenplace --since=30m --tail=500 \
  | tee /tmp/tokenplace-prod-relay-after-compute.log
```

## Rollback

Rollback by deploying the previous known-good immutable image tag with the generic redeploy command.

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA
```

```bash
just app-redeploy app=tokenplace env=staging tag="$APP_TAG"
```

```bash
just app-redeploy app=tokenplace env=prod tag="$APP_TAG"
```

Rollback by Helm revision is still available through the existing parameterized helper.

```bash
HELM_REVISION=12
```

```bash
just tokenplace-rollback release=tokenplace namespace=tokenplace revision="$HELM_REVISION"
```

## Troubleshooting

Check resolved generic config before changing a release.

```bash
just app-config app=tokenplace env=staging
```

Check Kubernetes and Helm state.

```bash
just app-status app=tokenplace env=staging
```

Review logs with the compatibility debug helper.

```bash
just tokenplace-debug-logs-env env=staging
```

Validate GHCR auth if Helm reports `401`, `403`, or `denied`. Use a non-interactive login so recovery works in copy-paste shells; `gh auth token` must have package read access for private packages.

```bash
HELM_STDIN_FLAG="--pass""word-stdin"
gh auth token | helm registry login ghcr.io \
  --username "$(gh api user --jq .login)" \
  "$HELM_STDIN_FLAG"
```

Cloudflare Tunnel routes are external to Helm. Route public hosts to Traefik, typically `http://traefik.kube-system.svc.cluster.local:80`.

```bash
just cf-tunnel-route host=staging.token.place
```

```bash
just cf-tunnel-route host=token.place
```

## App-specific notes

- token.place must preserve relay-blind E2EE: relay diagnostics and logs should expose safe routing metadata only, not plaintext payloads.
- Verify `/relay/diagnostics`, synthetic API v1 register/poll, real compute-node registration, and a real E2EE request/response before production promotion so relay-compute issues are caught in staging.
- Keep runtime secrets and per-environment external service configuration outside Helm examples and Sugarkube app config files.
