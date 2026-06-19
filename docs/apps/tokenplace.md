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
| Verify paths | `/`, `/livez`, `/healthz`, `/relay/diagnostics`, `/api/v1/meta` |

### Artifact links

Use these links before changing a deployment so the workflow runs, package versions, and source paths all agree.

| Artifact | Link |
| --- | --- |
| App repository | [token.place app repository](https://github.com/futuroptimist/token.place) |
| Image workflow | [Recent image workflow runs](https://github.com/futuroptimist/token.place/actions/workflows/ci-image.yml) |
| Successful main image runs | [Successful main image workflow runs](https://github.com/futuroptimist/token.place/actions/workflows/ci-image.yml?query=branch%3Amain+is%3Asuccess) |
| GHCR image package | [GHCR image package versions](https://github.com/futuroptimist/token.place/pkgs/container/tokenplace-relay) |
| Chart workflow | [Recent chart workflow runs](https://github.com/futuroptimist/token.place/actions/workflows/ci-helm.yml) |
| GHCR chart package | [GHCR chart package versions](https://github.com/futuroptimist/token.place/pkgs/container/charts%2Ftokenplace) |
| Dockerfile | [Application Dockerfile](https://github.com/futuroptimist/token.place/blob/main/Dockerfile) |
| Chart source | [Helm chart source](https://github.com/futuroptimist/token.place/tree/main/charts/tokenplace) |
| App release guide | [Sugarkube release guide in the app repo](https://github.com/futuroptimist/token.place/blob/main/docs/ops/sugarkube-release.md) |

## Environment topology

- `env=dev`: local/dev defaults using `docs/examples/tokenplace.values.dev.yaml`.
- `env=staging`: staging host `staging.token.place` with values `docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.staging.yaml`.
- `env=prod`: production host `token.place` with values `docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.prod.yaml`.
- token.place may depend on external compute-node or upstream runtime configuration; keep secrets and per-environment runtime config out of Sugarkube docs and app config files.

## Find or publish GHCR image

Find the successful image workflow in the token.place app repo and copy the immutable branch-SHA or release tag. The GitHub Actions workflow page is where recent builds are found; the GHCR package page is where published image tags are cross-checked. Do not deploy `latest`, a bare branch name, or an environment name.

Web UI shortcuts:

- Open [recent image workflow runs](https://github.com/futuroptimist/token.place/actions/workflows/ci-image.yml) or [successful main image runs](https://github.com/futuroptimist/token.place/actions/workflows/ci-image.yml?query=branch%3Amain+is%3Asuccess).
- Open [GHCR image package versions](https://github.com/futuroptimist/token.place/pkgs/container/tokenplace-relay).
- Copy the immutable tag from a successful workflow summary or package version.

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

The token.place image tag and Helm chart version are independent coordinates. `just app-deploy app=tokenplace tag=...` deploys the requested image tag with the chart version already pinned in `docs/apps/tokenplace.version`; it never silently selects the newest chart. Run the status command before deployment and commit intentional pin bumps when the app repo publishes chart wiring changes.

```bash
just app-chart-status app=tokenplace
```

If status reports a stale pin after a new chart is published, bump it explicitly:

```bash
just app-chart-bump app=tokenplace version=0.1.3
git add docs/apps/tokenplace.version
git commit -m "Bump tokenplace chart pin to 0.1.3"
git push
```

Prefer this committed pin workflow over unpinned chart overrides, and never use `chart=latest` for production.


Sugarkube deploys the chart version pinned in `docs/apps/tokenplace.version`. Use [recent chart workflow runs](https://github.com/futuroptimist/token.place/actions/workflows/ci-helm.yml) to find chart publish attempts, [GHCR chart package versions](https://github.com/futuroptimist/token.place/pkgs/container/charts%2Ftokenplace) to confirm available immutable chart versions, and [the chart source](https://github.com/futuroptimist/token.place/tree/main/charts/tokenplace) to review the chart content that should match the pinned version.

```bash
CHART_VERSION=$(sed -e 's/#.*$//' -e '/^[[:space:]]*$/d' docs/apps/tokenplace.version | head -n 1)
```

```bash
helm show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version "$CHART_VERSION"
```

If the chart changed, bump the chart version in the token.place app repo and publish it there with [the chart workflow](https://github.com/futuroptimist/token.place/actions/workflows/ci-helm.yml); do not republish a different chart under an existing OCI version.

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

`just app-verify` discovers the public host, executes the configured HTTP paths, prints a per-path body preview, and exits non-zero if any check fails. Use `print_only=1` when you only want the curl commands for docs or troubleshooting.

```bash
just app-status app=tokenplace env=staging
```

```bash
just app-verify app=tokenplace env=staging
```

```bash
just app-verify app=tokenplace env=staging print_only=1
```

Optional manual fallback:

```bash
curl -fsS https://staging.token.place/healthz
```

```bash
curl -fsS https://staging.token.place/livez
```

```bash
curl -fsS https://staging.token.place/relay/diagnostics | jq .
```

```bash
curl -fsS https://staging.token.place/api/v1/meta | jq .
```

Staging metadata must not report `.version == "dev"` or a `.label` ending in ` dev`; the expected label includes the deployed image tag, for example `staging main-00797df`.


## Browser CORS verification

After staging HTTP verification, run the generic read-only CORS probe against the public API v1 browser contract:

```bash
just app-cors-verify app=tokenplace env=staging
```

The check sends an unrelated `Origin` (`https://cors-smoke.invalid` by default) to prove all-origin wildcard behavior. Expected behavior:

- Public API v1 responds with literal `Access-Control-Allow-Origin: *`; token.place owns this header in the application response.
- Credentialed CORS is disabled; `Access-Control-Allow-Credentials: true` must not be present.
- API v1 remains zero-auth and non-streaming for this browser contract.
- CORS applies to public API v1, not API v2.
- This check is separate from relay-compute E2EE sign-off and does not replace it.

Use a custom unrelated origin only when debugging a browser report:

```bash
just app-cors-verify app=tokenplace env=staging origin=https://unrelated-client.example
```

If the check fails, deploy a token.place image containing the application-owned API v1 CORS fix; do not add Sugarkube ingress middleware, ingress annotations, Cloudflare response-header rules, or another CORS layer.

### Staging relay-compute sign-off

`just app-status`, `just app-verify`, `/livez`, `/healthz`, `/`, and `/relay/diagnostics` are necessary but not sufficient for token.place promotion. Staging-to-prod promotion is blocked until the real relay-compute path passes, as defined in [the token.place Sugarkube onboarding contract](../tokenplace_sugarkube_onboarding.md#promotion-gate-ownership). Before production promotion, capture staging evidence for the real relay path:

- [ ] A real external desktop or compute node is configured for `staging.token.place`, registers to the staging relay, and appears in staging `/healthz` and `/relay/diagnostics`.
- [ ] A real E2EE request/response succeeds through that staging-registered compute node.
- [ ] Release evidence records the chart digest, image tag, deployment YAML, health/diagnostics responses, and relay logs from after the staging compute test.

Do not replace this sign-off with synthetic register/poll, web/TLS readiness, health endpoints, or relay diagnostics alone. If the exact desktop or compute-node relay-test command is not documented for the release candidate, keep this as an operator checklist and attach the captured evidence instead of inventing a command.

## Promote production

Promote only after staging sign-off proves that a real external desktop or compute node registered with staging and completed a real E2EE request/response through the relay. Prefer the generic command; it uses the prod values chain and can read `docs/apps/tokenplace.prod.tag` when `tag=` is omitted.

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

Print the generated curl commands without executing them when you need a manual fallback:

```bash
just app-verify app=tokenplace env=prod print_only=1
```

Optional manual fallback:

```bash
curl -fsS https://token.place/healthz
```

```bash
curl -fsS https://token.place/livez
```

```bash
curl -fsS https://token.place/api/v1/meta | jq .
```

Production metadata must not report `.version == "dev"`; the expected label is a finalized release such as `prod 0.1.1`.

```bash
curl -fsS https://token.place/relay/diagnostics | jq .
```


Run the same API v1 CORS contract check before and after production promotion when validating a release candidate:

```bash
just app-cors-verify app=tokenplace env=prod
```

Production must also return literal `Access-Control-Allow-Origin: *`, keep credentialed CORS disabled, and leave CORS ownership in token.place rather than Sugarkube or Cloudflare.

### Production relay-compute proof

Do not mark production healthy on generic HTTP checks alone. After promotion, prove the production relay path separately from staging:

- [ ] A real desktop or compute node is configured for `token.place`, registers to production, and does not silently fall back to staging.
- [ ] The production-registered compute node appears in production `/healthz` and `/relay/diagnostics`.
- [ ] A real E2EE request/response succeeds through the production-registered compute node.
- [ ] Evidence is captured after the production E2EE test so health, diagnostics, and logs prove the real prod relay-compute path passed.

```bash
TOKENPLACE_HOST=token.place
kubectl --context sugar-prod -n tokenplace get deploy tokenplace -o yaml > /tmp/tokenplace-prod-deployment.yaml
# First run production desktop or compute-node registration and the
# production E2EE request/response. Then capture post-test evidence:
curl -fsS "https://${TOKENPLACE_HOST}/healthz" | tee /tmp/tokenplace-prod-healthz.json
curl -fsS "https://${TOKENPLACE_HOST}/relay/diagnostics" | tee /tmp/tokenplace-prod-diagnostics.json
kubectl --context sugar-prod -n tokenplace logs deploy/tokenplace --since=30m --tail=500 \
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

Rollback by Helm revision is still available through the existing parameterized helper. Set `ROLLBACK_ENV=staging` instead when intentionally rolling back staging.

```bash
HELM_REVISION=12
```

```bash
ROLLBACK_ENV=prod
just kubeconfig-env "$ROLLBACK_ENV"
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
- Verify `/relay/diagnostics`, real external compute-node registration, and a real E2EE request/response before production promotion so relay-compute issues are caught in staging.
- Keep runtime secrets and per-environment external service configuration outside Helm examples and Sugarkube app config files.
