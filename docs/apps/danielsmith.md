# danielsmith.io on Sugarkube

This is the canonical runbook for deploying danielsmith.io from GHCR artifacts to Sugarkube. The generic `just app-*` recipes are the preferred future path. The `danielsmith-oci-*` recipes remain compatibility shims and are scheduled for later removal only after the generic flow has been exercised across routine releases.

## Artifact model

- App repository responsibilities: build `ghcr.io/futuroptimist/danielsmith.io`, publish immutable image tags, maintain the Helm chart, and publish immutable chart versions to `oci://ghcr.io/futuroptimist/charts/danielsmith`.
- Sugarkube responsibilities: select `dev`, `staging`, or `prod`; load `docs/examples/apps/danielsmith.env` or a local override; select kubeconfig/context; install or upgrade Helm; verify rollout status, logs, and public paths.
- Cloudflare responsibilities: DNS and Tunnel routes to Traefik are outside Helm and must exist before public verification.

| Coordinate | Value |
| --- | --- |
| Image | `ghcr.io/futuroptimist/danielsmith.io` |
| Chart | `oci://ghcr.io/futuroptimist/charts/danielsmith` |
| Release | `danielsmith` |
| Namespace | `danielsmith` |
| App config | `docs/examples/apps/danielsmith.env` |
| Chart version pin | `docs/apps/danielsmith.version` |
| Production tag pin | `docs/apps/danielsmith.prod.tag` |
| Verify paths | `/`, `/livez`, `/healthz`, `/runtime/github-metrics.json` |

### Artifact links

Use these links before changing a deployment so the workflow runs, package versions, and source paths all agree.

| Artifact | Link |
| --- | --- |
| App repository | [danielsmith.io app repository](https://github.com/futuroptimist/danielsmith.io) |
| Image workflow | [Recent image workflow runs](https://github.com/futuroptimist/danielsmith.io/actions/workflows/ci-image.yml) |
| Successful main image runs | [Successful main image workflow runs](https://github.com/futuroptimist/danielsmith.io/actions/workflows/ci-image.yml?query=branch%3Amain+is%3Asuccess) |
| GHCR image package | [GHCR image package versions](https://github.com/futuroptimist/danielsmith.io/pkgs/container/danielsmith.io) |
| Chart workflow | [Recent chart workflow runs](https://github.com/futuroptimist/danielsmith.io/actions/workflows/ci-helm.yml) |
| GHCR chart package | [GHCR chart package versions](https://github.com/futuroptimist/danielsmith.io/pkgs/container/charts%2Fdanielsmith) |
| Dockerfile | [Application Dockerfile](https://github.com/futuroptimist/danielsmith.io/blob/main/Dockerfile) |
| Chart source | [Helm chart source](https://github.com/futuroptimist/danielsmith.io/tree/main/charts/danielsmith) |
| App release guide | [Sugarkube release guide in the app repo](https://github.com/futuroptimist/danielsmith.io/blob/main/docs/ops/sugarkube-release.md) |

## Environment topology

- `env=dev`: local/dev defaults using `docs/examples/danielsmith.values.dev.yaml`.
- `env=staging`: staging host `staging.danielsmith.io` with values `docs/examples/danielsmith.values.dev.yaml,docs/examples/danielsmith.values.staging.yaml`.
- `env=prod`: production host `danielsmith.io` with values `docs/examples/danielsmith.values.dev.yaml,docs/examples/danielsmith.values.prod.yaml`.
- The app is a static Vite and Three.js site. Sugarkube runs the static web container only; no in-cluster API, queue, database, GPU, compute node, or stateful service is required.


## Runtime GitHub metrics cache

Staging and production enable the chart's `githubMetricsCache` sidecar so visitor browsers do not call GitHub directly for project star counts. The pod runs the normal nginx/static-site container plus a small sidecar container named `github-metrics-cache`. Both containers share an `emptyDir` volume: the sidecar refreshes a JSON cache atomically, and nginx serves the file to browsers at `/runtime/github-metrics.json`.

The current portfolio star flow uses only public repository metadata from public GitHub repositories. The sidecar calls the unauthenticated public GitHub REST API and does **not** need a GitHub token, GitHub App credential, Kubernetes Secret, `envFrom` Secret, or any other authenticated API path. Do not add placeholder token values to Sugarkube for this flow; if the public unauthenticated rate limit is hit, treat it as an operations signal to inspect logs and staleness rather than a secret-management task.

Sugarkube pins the sidecar-capable danielsmith chart in `docs/apps/danielsmith.version` and enables the cache from the staging and prod values overlays. The configured repository list intentionally includes public POI repositories only: `futuroptimist/danielsmith.io`, `futuroptimist/token.place`, `futuroptimist/gabriel`, `futuroptimist/flywheel`, `futuroptimist/jobbot3000`, `futuroptimist/gitshelves`, `futuroptimist/f2clipboard`, `futuroptimist/sigma`, `futuroptimist/wove`, `democratizedspace/dspace`, and `futuroptimist/pr-reaper`. Do not add private repositories unless they are publicly fetchable without credentials.

The refresh interval is hourly (`refreshIntervalSeconds: 3600`). The cache TTL is longer than one interval so a single late refresh or brief GitHub outage does not cause visible churn; in normal operation displayed stars can be up to about an hour old. If GitHub is unavailable on startup or a refresh fails, the sidecar should keep or write a valid neutral JSON document so the app avoids presenting fake fallback star counts as facts.

`just app-verify` includes the runtime cache path for danielsmith staging and production so deploy verification confirms nginx can serve the sidecar-backed file. The generic verifier only checks HTTP status and body preview; run the JSON checks below when validating schema details.

### Verify the runtime cache

Staging:

```bash
curl -fsS https://staging.danielsmith.io/runtime/github-metrics.json
```

```bash
kubectl --context sugar-staging -n danielsmith logs deploy/danielsmith -c github-metrics-cache --tail=100
```

```bash
curl -fsS https://staging.danielsmith.io/runtime/github-metrics.json \
  | python3 -m json.tool
```

```bash
python3 - <<'PY'
import json
import urllib.request

url = 'https://staging.danielsmith.io/runtime/github-metrics.json'
with urllib.request.urlopen(url, timeout=10) as response:
    data = json.load(response)

assert data.get('schemaVersion')
assert data.get('generatedAt')
repos = data.get('repos')
assert isinstance(repos, dict)
for key in (
    'futuroptimist/danielsmith.io',
    'futuroptimist/token.place',
    'futuroptimist/flywheel',
    'democratizedspace/dspace',
):
    assert key in repos, f'missing {key}'
print(f"schemaVersion={data['schemaVersion']} generatedAt={data['generatedAt']} repos={len(repos)}")
PY
```

Production uses the same checks with the production host and context:

```bash
curl -fsS https://danielsmith.io/runtime/github-metrics.json
```

```bash
kubectl --context sugar-prod -n danielsmith logs deploy/danielsmith -c github-metrics-cache --tail=100
```

## Find or publish GHCR image

Find the successful image workflow in the danielsmith.io app repo and copy the immutable branch-SHA or release tag. The GitHub Actions workflow page is where recent builds are found; the GHCR package page is where published image tags are cross-checked. Do not deploy `latest`, a bare branch name, or an environment name.

Web UI shortcuts:

- Open [recent image workflow runs](https://github.com/futuroptimist/danielsmith.io/actions/workflows/ci-image.yml) or [successful main image runs](https://github.com/futuroptimist/danielsmith.io/actions/workflows/ci-image.yml?query=branch%3Amain+is%3Asuccess).
- Open [GHCR image package versions](https://github.com/futuroptimist/danielsmith.io/pkgs/container/danielsmith.io).
- Copy the immutable tag from a successful workflow summary or package version.

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
gh run list --repo futuroptimist/danielsmith.io --workflow ci-image.yml --branch main --status success --limit 5
```

If no suitable image exists, publish it from the app repo workflow, then return here with the immutable tag it produced.

```bash
gh workflow run ci-image.yml --repo futuroptimist/danielsmith.io --ref main
```

## Confirm/publish OCI chart

Sugarkube deploys the chart version pinned in `docs/apps/danielsmith.version`. Use [recent chart workflow runs](https://github.com/futuroptimist/danielsmith.io/actions/workflows/ci-helm.yml) to find chart publish attempts, [GHCR chart package versions](https://github.com/futuroptimist/danielsmith.io/pkgs/container/charts%2Fdanielsmith) to confirm available immutable chart versions, and [the chart source](https://github.com/futuroptimist/danielsmith.io/tree/main/charts/danielsmith) to review the chart content that should match the pinned version.

```bash
CHART_VERSION=$(sed -e 's/#.*$//' -e '/^[[:space:]]*$/d' docs/apps/danielsmith.version | head -n 1)
```

```bash
helm show chart oci://ghcr.io/futuroptimist/charts/danielsmith --version "$CHART_VERSION"
```

If the chart changed, bump the chart version in the danielsmith.io app repo and publish it there with [the chart workflow](https://github.com/futuroptimist/danielsmith.io/actions/workflows/ci-helm.yml); do not republish a different chart under an existing OCI version.

```bash
gh workflow run ci-helm.yml --repo futuroptimist/danielsmith.io --ref main
```

## Deploy staging

Preferred generic command:

```bash
just app-deploy app=danielsmith env=staging tag="$APP_TAG"
```

Compatibility shim while migration is in progress:

```bash
just danielsmith-oci-deploy env=staging tag="$APP_TAG"
```

## Verify staging

`just app-verify` discovers the public host, executes the configured HTTP paths, prints a per-path body preview, and exits non-zero if any check fails. Use `print_only=1` when you only want the curl commands for docs or troubleshooting.

```bash
just app-status app=danielsmith env=staging
```

```bash
just app-verify app=danielsmith env=staging
```

```bash
just app-verify app=danielsmith env=staging print_only=1
```

Optional manual fallback when debugging DNS, TLS, or Cloudflare behavior:

```bash
curl -fsS https://staging.danielsmith.io/healthz
curl -fsS https://staging.danielsmith.io/livez
curl -fsS https://staging.danielsmith.io/runtime/github-metrics.json
curl -fsS https://staging.danielsmith.io/
```

## Promote production

Promote only after staging sign-off. Prefer the generic command; it uses the prod values chain and can read `docs/apps/danielsmith.prod.tag` when `tag=` is omitted.

```bash
just app-promote-prod app=danielsmith tag="$APP_TAG"
```

Compatibility shim:

```bash
just danielsmith-oci-promote-prod tag="$APP_TAG"
```

## Verify production

```bash
just app-status app=danielsmith env=prod
```

```bash
just app-verify app=danielsmith env=prod
```

Print the generated curl commands without executing them when you need a manual fallback:

```bash
just app-verify app=danielsmith env=prod print_only=1
```

```bash
curl -fsS https://danielsmith.io/healthz
```

```bash
curl -fsS https://danielsmith.io/livez
```

```bash
curl -fsS https://danielsmith.io/runtime/github-metrics.json
```

```bash
curl -fsS https://danielsmith.io/
```

## Rollback

Rollback by deploying the previous known-good immutable image tag with the generic redeploy command.

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA
```

```bash
just app-redeploy app=danielsmith env=staging tag="$APP_TAG"
```

```bash
just app-redeploy app=danielsmith env=prod tag="$APP_TAG"
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
just tokenplace-rollback release=danielsmith namespace=danielsmith revision="$HELM_REVISION"
```

## Troubleshooting

Check resolved generic config before changing a release.

```bash
just app-config app=danielsmith env=staging
```

Check Kubernetes and Helm state.

```bash
just app-status app=danielsmith env=staging
```

Review logs with the compatibility debug helper.

```bash
just danielsmith-debug-logs-env env=staging
```

Validate GHCR auth if Helm reports `401`, `403`, or `denied`. Use a non-interactive login so recovery works in copy-paste shells; `gh auth token` must have package read access for private packages.

```bash
HELM_STDIN_FLAG="--pass""word-stdin"
gh auth token | helm registry login ghcr.io \
  --username "$(gh api user --jq .login)" \
  "$HELM_STDIN_FLAG"
```


### Runtime GitHub metrics cache

If `/runtime/github-metrics.json` returns `404` or an empty response, confirm the deployed chart version includes the sidecar support, confirm the staging/prod values overlay has `githubMetricsCache.enabled: true`, then inspect the sidecar logs:

```bash
kubectl --context sugar-staging -n danielsmith logs deploy/danielsmith -c github-metrics-cache --tail=100
```

If logs mention GitHub rate limiting or transient GitHub failures, do not add a token by default. The current flow intentionally uses unauthenticated public metadata only. Check whether the existing cache remains within its TTL/grace window, retry after the public API limit resets, and only consider a future authenticated design in a separate secret-management change.

If the cache is stale, compare the JSON `generatedAt` and `expiresAt` fields with the current UTC time. One late hourly refresh should not create visible churn because `cacheTtlSeconds` is longer than `refreshIntervalSeconds`; repeated stale values usually mean the sidecar cannot reach GitHub or cannot write the shared cache volume.

Cloudflare Tunnel routes are external to Helm. Route public hosts to Traefik, typically `http://traefik.kube-system.svc.cluster.local:80`.

```bash
just cf-tunnel-route host=staging.danielsmith.io
```

```bash
just cf-tunnel-route host=danielsmith.io
```

## App-specific notes

- danielsmith.io is static-site only; a failing rollout is usually an image, chart, ingress, TLS, or Cloudflare issue rather than an in-cluster backend dependency.
- Verify `/` in addition to health endpoints so static assets and Traefik host routing are exercised before production promotion.
