# danielsmith.io on Sugarkube

Use this runbook for GHCR-first `danielsmith.io` deploys from published GitHub Actions artifacts to
Sugarkube. The generic app recipes are the preferred future path; the `danielsmith-*` recipes are
compatibility shims that stay documented until the generic flow has been exercised across routine
releases.

## 1. Artifact model

App repo responsibilities:

- Build and publish the static-site image to GHCR.
- Build and publish the Helm chart as an immutable OCI artifact.
- Keep static-site build and chart release notes in the app repository.

Sugarkube responsibilities:

- Select kubeconfig and environment.
- Read `docs/examples/apps/danielsmith.env` or a copied local `apps/danielsmith.env`.
- Run Helm deploys with the configured values overlays and chart version pin.
- Verify Kubernetes status, public HTTPS paths, and logs.

Cloudflare responsibilities:

- DNS and Cloudflare Tunnel routes are configured outside Helm.
- Route `staging.danielsmith.io` and `danielsmith.io` to Traefik before public HTTPS checks can
  pass.

Current artifact contract:

| Field | Value |
| --- | --- |
| Image | `ghcr.io/futuroptimist/danielsmith.io` |
| Chart | `oci://ghcr.io/futuroptimist/charts/danielsmith` |
| Release | `danielsmith` |
| Namespace | `danielsmith` |
| App config | `docs/examples/apps/danielsmith.env` |
| Chart version pin | `docs/apps/danielsmith.version` |
| Production tag pin | `docs/apps/danielsmith.prod.tag` |
| Verify paths | `/`, `/livez`, `/healthz` |

## 2. Environment topology

Values overlays decide routing; image tags decide the static-site build.

| Environment | Sugarkube values chain | Public host |
| --- | --- | --- |
| `dev` | `docs/examples/danielsmith.values.dev.yaml` | Local/dev only unless overridden |
| `staging` | `docs/examples/danielsmith.values.dev.yaml,docs/examples/danielsmith.values.staging.yaml` | `staging.danielsmith.io` |
| `prod` | `docs/examples/danielsmith.values.dev.yaml,docs/examples/danielsmith.values.prod.yaml` | `danielsmith.io` |

`danielsmith.io` is a static Vite and Three.js site. Sugarkube runs only the static web container;
there is no in-cluster API, database, queue, GPU worker, or stateful service for this app.

## 3. Find or publish GHCR image

Find the successful image workflow run in the `danielsmith.io` app repo, then copy its immutable
image tag. Prefer branch-SHA tags such as `main-REPLACE_SHORTSHA` or semver release tags. Do not
deploy mutable tags such as `latest`, `main`, `staging`, or `prod` through the generic recipes.

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

Validate the tag shape locally before deploying:

```bash
python3 scripts/app_config.py validate-tag "$APP_TAG"
```

If no immutable image exists yet, publish one from the app repo's image workflow, then return here
with the resulting GHCR tag. Local `docker build` commands are for app-repo development only, not
Sugarkube staging or production deploys.

## 4. Confirm/publish OCI chart

Confirm Sugarkube can read the pinned chart version:

```bash
CHART_VERSION=$(sed -e 's/#.*$//' -e '/^[[:space:]]*$/d' docs/apps/danielsmith.version | head -n1)
```

```bash
helm show chart oci://ghcr.io/futuroptimist/charts/danielsmith --version "$CHART_VERSION"
```

If the chart changed in the `danielsmith.io` app repo, publish a new immutable OCI chart there
first and then update `docs/apps/danielsmith.version` in Sugarkube. If only the image changed, keep
the chart version pin unchanged.

## 5. Deploy staging

Preferred generic deploy:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just app-deploy app=danielsmith env=staging tag="$APP_TAG"
```

Compatibility wrapper while the generic flow bakes in:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just danielsmith-oci-deploy env=staging tag="$APP_TAG"
```

## 6. Verify staging

Generic HTTPS smoke checks from the app config:

```bash
just app-verify app=danielsmith env=staging
```

Kubernetes status with the generic app config:

```bash
just app-status app=danielsmith env=staging
```

Compatibility status/log helpers:

```bash
just danielsmith-status
```

```bash
just danielsmith-debug-logs-env env=staging
```

Manual public checks when you need the exact commands:

```bash
curl -fsS https://staging.danielsmith.io/
```

```bash
curl -fsS https://staging.danielsmith.io/livez
```

```bash
curl -fsS https://staging.danielsmith.io/healthz
```

## 7. Promote production

Promote only the exact immutable tag that passed staging.

Preferred generic production promotion:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just app-promote-prod app=danielsmith tag="$APP_TAG"
```

Compatibility wrapper:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just danielsmith-oci-promote-prod tag="$APP_TAG"
```

If `docs/apps/danielsmith.prod.tag` has already been reviewed and pinned to the approved tag, both
production promotion recipes can read it when `tag=` is omitted. Passing `tag=` is still clearer for
copy-pasteable release notes.

## 8. Verify production

Generic HTTPS smoke checks:

```bash
just app-verify app=danielsmith env=prod
```

Generic status:

```bash
just app-status app=danielsmith env=prod
```

Manual public checks:

```bash
curl -fsS https://danielsmith.io/
```

```bash
curl -fsS https://danielsmith.io/livez
```

```bash
curl -fsS https://danielsmith.io/healthz
```

## 9. Rollback

Prefer immutable-tag rollback when the bad release maps to a single image tag:

```bash
PREVIOUS_TAG=main-REPLACE_PREVIOUS_SHORTSHA
```

```bash
just app-deploy app=danielsmith env=prod tag="$PREVIOUS_TAG"
```

Use Helm revision rollback when you must restore the full rendered release state:

```bash
HELM_REVISION=12
```

```bash
just tokenplace-rollback release=danielsmith namespace=danielsmith revision="$HELM_REVISION"
```

`tokenplace-rollback` is a generic parameterized Helm rollback helper despite its legacy name.

## 10. Troubleshooting

GHCR auth failures usually look like `401`, `403`, or `denied`. Log in and retry the chart check:

```bash
helm registry login ghcr.io -u "$GHCR_USER"
```

```bash
helm show chart oci://ghcr.io/futuroptimist/charts/danielsmith --version "$CHART_VERSION"
```

Check rendered app config before deploying:

```bash
just app-config app=danielsmith env=staging
```

Inspect cluster state and ingress routing:

```bash
just cluster-status
```

```bash
just traefik-status
```

```bash
just cf-tunnel-debug
```

Create or refresh Cloudflare Tunnel routes outside Helm when DNS is the blocker:

```bash
just cf-tunnel-route host=staging.danielsmith.io
```

```bash
just cf-tunnel-route host=danielsmith.io
```

## 11. App-specific notes

- `danielsmith.io` has no runtime secrets in the Sugarkube example overlays.
- The primary app smoke checks are static page availability plus `/livez` and `/healthz`.
- If the static-site chart changes without an image rebuild, bump only the chart version and keep
  the last approved image tag.
