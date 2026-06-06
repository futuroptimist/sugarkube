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
| Verify paths | `/`, `/livez`, `/healthz` |

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

Staging and production enable the danielsmith.io Helm chart's `githubMetricsCache` sidecar. The main nginx container serves the static portfolio, while the sidecar wakes up about once an hour, calls the unauthenticated public GitHub repository API for the configured public POI repositories, and writes a shared cache file to the pod-local runtime volume. nginx exposes that file to visitors at `/runtime/github-metrics.json`, so browsers read same-origin JSON instead of each visitor spending their own GitHub API rate limit.

The current public stars flow does **not** require a GitHub token, Kubernetes Secret, `envFrom` Secret, or authenticated API path. Keep the cache unauthenticated unless a future feature needs private repository metadata. The configured repo list mirrors only the public POI GitHub star sources from the app repo and intentionally omits private-only sources. DSPACE star metrics are public and come from `democratizedspace/dspace`. The same sidecar target list also includes `futuroptimist/sugarkube` and `futuroptimist/axel` so the Sugarkube and Axel POIs read from the runtime cache.

The sidecar uses `refreshIntervalSeconds: 3600`. Its `cacheTtlSeconds: 7200` value gives the browser cache enough grace to avoid visible metric churn when one hourly refresh is late, so displayed stars can normally be up to about an hour old and may briefly remain older during GitHub outages or rate-limit windows.

Staging/prod values enable the cache; dev remains disabled by the base values unless a local operator intentionally overrides it for chart testing. Because `SUGARKUBE_VERIFY_PATHS` is defined once per app config and shared by dev/staging/prod, the generic verify path list intentionally stays at `/`, `/livez`, and `/healthz`. `app-verify` cannot currently express staging/prod-only runtime JSON checks or optional paths safely, so keep `/runtime/github-metrics.json` as the required manual staging/prod sidecar verification path instead of adding it to the shared app config.

### Verify the runtime cache

`just app-verify` confirms the shared HTTP paths after deploy. The sidecar cache is not signed off until the manual curl/jq/log checks below also pass for staging or production. Run the staging sequence after `just app-verify app=danielsmith env=staging` when validating the sidecar content and logs:

```bash
just app-verify app=danielsmith env=staging
```

```bash
curl -fsS https://staging.danielsmith.io/runtime/github-metrics.json
```

```bash
curl -fsS https://staging.danielsmith.io/runtime/github-metrics.json | jq -e '.schemaVersion == 1 and (.generatedAt | type == "string") and (.repos | type == "object")'
```

```bash
curl -fsS https://staging.danielsmith.io/runtime/github-metrics.json | jq -e '(.repos["futuroptimist/danielsmith.io"].stars | type == "number") and (.repos["democratizedspace/dspace"].stars | type == "number")'
```

```bash
kubectl --context sugar-staging -n danielsmith logs deploy/danielsmith -c github-metrics --tail=100
```

For production sidecar sign-off, run `just app-verify app=danielsmith env=prod`, then repeat the required manual curl/jq/log checks with `https://danielsmith.io/runtime/github-metrics.json` and `--context sugar-prod`.

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
curl -fsS https://staging.danielsmith.io/
curl -fsS https://staging.danielsmith.io/runtime/github-metrics.json
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
curl -fsS https://danielsmith.io/
```

```bash
curl -fsS https://danielsmith.io/runtime/github-metrics.json
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

If `/runtime/github-metrics.json` is missing or returns a non-200 status, first confirm staging/prod were deployed with values that enable `githubMetricsCache.enabled`, then inspect the sidecar logs. The expected staging log command is:

```bash
kubectl --context sugar-staging -n danielsmith logs deploy/danielsmith -c github-metrics --tail=100
```

If logs mention GitHub `403`, `429`, or rate limiting, do not add a token as the first response. The current flow only uses public stars and is intentionally unauthenticated; the sidecar should retry on the next hourly refresh while the browser keeps neutral or stale-safe copy. Confirm the repo list contains only public POI repos and wait for the rate-limit window to reset.

If the cache is stale, compare `generatedAt` and `expiresAt` in the JSON payload. The chart refreshes hourly and keeps a two-hour TTL so one delayed refresh does not make visitors see metric churn. Staleness beyond that points to sidecar crashes, egress/DNS problems, GitHub rate limiting, or a mounted-cache path mismatch.

Do not configure a GitHub token, placeholder token, Kubernetes Secret, or `envFrom` Secret for this public stars cache. Secret-management recipes are out of scope for this flow and should only be added if a future authenticated feature is explicitly approved.

Validate GHCR auth if Helm reports `401`, `403`, or `denied`. Use a non-interactive login so recovery works in copy-paste shells; `gh auth token` must have package read access for private packages.

```bash
HELM_STDIN_FLAG="--pass""word-stdin"
gh auth token | helm registry login ghcr.io \
  --username "$(gh api user --jq .login)" \
  "$HELM_STDIN_FLAG"
```

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
