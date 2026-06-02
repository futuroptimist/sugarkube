# danielsmith.io on Sugarkube

Use this runbook for GHCR-first danielsmith.io deploys, promotions,
verification, and rollback on Sugarkube. The preferred future path is the generic
app flow backed by `docs/examples/apps/danielsmith.env`; the `danielsmith-*`
recipes remain compatibility shims until the generic flow has been exercised
across routine releases.

## 1. Artifact model

- App repository responsibility: build and publish
  `ghcr.io/futuroptimist/danielsmith.io` static-site images from the
  danielsmith.io repository's CI, including immutable deploy tags such as
  `main-REPLACE_SHORTSHA`.
- App repository responsibility: package and publish the Helm chart at
  `oci://ghcr.io/futuroptimist/charts/danielsmith` with immutable chart versions.
- Sugarkube responsibility: select kubeconfig/environment, read
  `docs/examples/apps/danielsmith.env`, pin the chart version from
  `docs/apps/danielsmith.version`, deploy the selected image tag with Helm, and
  run status/verify/log helpers.
- Cloudflare responsibility: DNS and tunnel routes for the public hostnames live
  outside Helm; the chart only creates Kubernetes resources behind Traefik.

| Coordinate | Value |
| --- | --- |
| App config | `docs/examples/apps/danielsmith.env` |
| Image | `ghcr.io/futuroptimist/danielsmith.io` |
| Chart | `oci://ghcr.io/futuroptimist/charts/danielsmith` |
| Release | `danielsmith` |
| Namespace | `danielsmith` |
| Chart pin | `docs/apps/danielsmith.version` |
| Production tag pin | `docs/apps/danielsmith.prod.tag` |
| Verify paths | `/`, `/livez`, `/healthz` |

## 2. Environment topology

- `env=dev`: non-production defaults using
  `docs/examples/danielsmith.values.dev.yaml`.
- `env=staging`: staging host `staging.danielsmith.io`, values chain
  `docs/examples/danielsmith.values.dev.yaml,docs/examples/danielsmith.values.staging.yaml`.
- `env=prod`: production host `danielsmith.io`, values chain
  `docs/examples/danielsmith.values.dev.yaml,docs/examples/danielsmith.values.prod.yaml`.

## 3. Find or publish GHCR image

Find the latest successful danielsmith.io image workflow and copy the immutable
tag it published.

```bash
APP_TAG=main-REPLACE_SHORTSHA # replace with the immutable GHCR image tag from danielsmith.io CI
```

```bash
gh run list --repo futuroptimist/danielsmith.io --workflow ci-image.yml --status success --limit 10
```

If no usable immutable tag exists, publish one from the danielsmith.io
repository's image workflow before deploying from Sugarkube.

```bash
gh workflow run ci-image.yml --repo futuroptimist/danielsmith.io --ref main
```

## 4. Confirm/publish OCI chart

Sugarkube reads the chart version from `docs/apps/danielsmith.version`. Confirm
that GHCR has that chart before deploying.

```bash
CHART_VERSION=$(grep -E '^[0-9]+\.[0-9]+\.[0-9]+' docs/apps/danielsmith.version | head -n1)
```

```bash
helm show chart oci://ghcr.io/futuroptimist/charts/danielsmith --version "$CHART_VERSION"
```

If the chart changed in the danielsmith.io repository and GHCR does not have the
desired version yet, publish it from the chart workflow before updating the
Sugarkube chart pin.

```bash
gh workflow run ci-helm.yml --repo futuroptimist/danielsmith.io --ref main
```

## 5. Deploy staging

Preferred generic command:

```bash
APP_TAG=main-REPLACE_SHORTSHA # replace with the immutable GHCR image tag from danielsmith.io CI
just app-deploy app=danielsmith env=staging tag="$APP_TAG"
```

Current compatibility wrapper:

```bash
APP_TAG=main-REPLACE_SHORTSHA # replace with the immutable GHCR image tag from danielsmith.io CI
just danielsmith-oci-deploy env=staging tag="$APP_TAG"
```

## 6. Verify staging

```bash
just app-status app=danielsmith env=staging
```

```bash
just app-verify app=danielsmith env=staging
```

```bash
curl -fsS https://staging.danielsmith.io/livez
```

```bash
curl -fsS https://staging.danielsmith.io/healthz
```

```bash
curl -fsS https://staging.danielsmith.io/
```

## 7. Promote production

Promote only after staging sign-off. Record the approved immutable tag in your
release notes and, when appropriate, in `docs/apps/danielsmith.prod.tag`.

Preferred generic command:

```bash
APP_TAG=main-REPLACE_SHORTSHA # replace with the staging-approved immutable GHCR image tag
just app-promote-prod app=danielsmith tag="$APP_TAG"
```

Current compatibility wrapper:

```bash
APP_TAG=main-REPLACE_SHORTSHA # replace with the staging-approved immutable GHCR image tag
just danielsmith-oci-promote-prod tag="$APP_TAG"
```

If `docs/apps/danielsmith.prod.tag` already contains the approved production tag,
the generic promotion command can read it by omitting `tag=`.

```bash
just app-promote-prod app=danielsmith
```

## 8. Verify production

```bash
just app-status app=danielsmith env=prod
```

```bash
just app-verify app=danielsmith env=prod
```

```bash
curl -fsS https://danielsmith.io/livez
```

```bash
curl -fsS https://danielsmith.io/healthz
```

```bash
curl -fsS https://danielsmith.io/
```

## 9. Rollback

Rollback by immutable tag with the generic redeploy helper:

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA # replace with the previous known-good immutable GHCR image tag
just app-redeploy app=danielsmith env=prod tag="$APP_TAG"
```

Rollback staging the same way if the failure is caught before promotion:

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA # replace with the previous known-good immutable GHCR image tag
just app-redeploy app=danielsmith env=staging tag="$APP_TAG"
```

Rollback by Helm revision when a revision number is known:

```bash
DANIELSMITH_REVISION=12 # replace with the known-good Helm revision
just tokenplace-rollback release=danielsmith namespace=danielsmith revision="$DANIELSMITH_REVISION"
```

## 10. Troubleshooting

GHCR authentication and chart pull failures commonly show up as Helm `401` or
`403` errors. Log in to GHCR with a package-read credential, then retry the
chart check.

```bash
CHART_VERSION=$(grep -E '^[0-9]+\.[0-9]+\.[0-9]+' docs/apps/danielsmith.version | head -n1)
helm show chart oci://ghcr.io/futuroptimist/charts/danielsmith --version "$CHART_VERSION"
```

Inspect status, logs, ingress, and tunnel routing:

```bash
just app-status app=danielsmith env=staging
```

```bash
just danielsmith-debug-logs-env env=staging
```

```bash
just cluster-status
```

```bash
just traefik-status
```

```bash
just cf-tunnel-debug
```

Cloudflare routes are external to Helm. Create or repair routes outside the
chart when DNS/tunnel routing is the failing layer.

```bash
just cf-tunnel-route host=staging.danielsmith.io
```

## 11. App-specific notes

- danielsmith.io is a static Vite/Three.js site; Sugarkube deploys only the
  static web container.
- No in-cluster API, database, queue, GPU, or stateful service is expected for
  the current site.
- Verify `/` as well as `/livez` and `/healthz` because the health endpoints can
  pass while a static asset routing regression affects the homepage.
