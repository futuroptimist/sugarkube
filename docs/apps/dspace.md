# democratized.space (dspace) on Sugarkube

Use this runbook for GHCR-first dspace deploys, promotions, verification, and
rollback on Sugarkube. The preferred future path is the generic app flow backed
by `docs/examples/apps/dspace.env`; the `dspace-*` recipes remain compatibility
shims until the generic flow has been exercised across routine releases.

## 1. Artifact model

- App repository responsibility: build and publish `ghcr.io/democratizedspace/dspace`
  images from the dspace repository's CI, including immutable deploy tags such
  as `main-REPLACE_SHORTSHA` or release tags such as `3.1.0`.
- App repository responsibility: package and publish the Helm chart at
  `oci://ghcr.io/democratizedspace/charts/dspace` with immutable chart versions.
- Sugarkube responsibility: select kubeconfig/environment, read
  `docs/examples/apps/dspace.env`, pin the chart version from
  `docs/apps/dspace.version`, deploy the selected image tag with Helm, and run
  status/verify/log helpers.
- Cloudflare responsibility: DNS and tunnel routes for the public hostnames live
  outside Helm; the chart only creates Kubernetes resources behind Traefik.

| Coordinate | Value |
| --- | --- |
| App config | `docs/examples/apps/dspace.env` |
| Image | `ghcr.io/democratizedspace/dspace` |
| Chart | `oci://ghcr.io/democratizedspace/charts/dspace` |
| Release | `dspace` |
| Namespace | `dspace` |
| Chart pin | `docs/apps/dspace.version` |
| Production tag pin | `docs/apps/dspace.prod.tag` |
| Verify paths | `/config.json`, `/healthz`, `/livez` |

## 2. Environment topology

- `env=dev`: future single-node/non-HA environment using
  `docs/examples/dspace.values.dev.yaml`.
- `env=staging`: HA staging on the staging Sugarkube cluster, public host
  `staging.democratized.space`, values chain
  `docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml`.
- `env=prod`: HA production on the production Sugarkube cluster, public host
  `democratized.space`, values chain
  `docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.prod.yaml`.
- Optional legacy production subdomain: `prod.democratized.space` uses
  `docs/examples/dspace.values.prod-subdomain.yaml` only when explicitly needed.

## 3. Find or publish GHCR image

Find the latest successful dspace image workflow in the dspace repository and
copy the immutable tag it published.

```bash
APP_TAG=main-REPLACE_SHORTSHA # replace with the immutable GHCR image tag from dspace CI
```

```bash
gh run list --repo democratizedspace/dspace --workflow ci-image.yml --status success --limit 10
```

If no usable immutable tag exists, publish one from the dspace repository's image
workflow before deploying from Sugarkube.

```bash
gh workflow run ci-image.yml --repo democratizedspace/dspace --ref main
```

## 4. Confirm/publish OCI chart

Sugarkube reads the chart version from `docs/apps/dspace.version`. Confirm that
GHCR has that chart before deploying.

```bash
CHART_VERSION=$(grep -E '^[0-9]+\.[0-9]+\.[0-9]+' docs/apps/dspace.version | head -n1)
```

```bash
helm show chart oci://ghcr.io/democratizedspace/charts/dspace --version "$CHART_VERSION"
```

If the chart changed in the dspace repository and GHCR does not have the desired
version yet, publish it from the dspace chart workflow before updating the
Sugarkube chart pin.

```bash
gh workflow run ci-helm.yml --repo democratizedspace/dspace --ref main
```

## 5. Deploy staging

Preferred generic command:

```bash
APP_TAG=main-REPLACE_SHORTSHA # replace with the immutable GHCR image tag from dspace CI
just app-deploy app=dspace env=staging tag="$APP_TAG"
```

Current compatibility wrapper:

```bash
APP_TAG=main-REPLACE_SHORTSHA # replace with the immutable GHCR image tag from dspace CI
just dspace-oci-deploy env=staging tag="$APP_TAG"
```

## 6. Verify staging

Run the generic Sugarkube status and HTTP verification helpers first.

```bash
just app-status app=dspace env=staging
```

```bash
just app-verify app=dspace env=staging
```

Manual smoke checks:

```bash
curl -fsS https://staging.democratized.space/config.json | jq .
```

```bash
curl -fsS https://staging.democratized.space/healthz
```

```bash
curl -fsS https://staging.democratized.space/livez
```

## 7. Promote production

Promote only after staging sign-off. Record the approved immutable tag in your
release notes and, when appropriate, in `docs/apps/dspace.prod.tag`.

Preferred generic command:

```bash
APP_TAG=main-REPLACE_SHORTSHA # replace with the staging-approved immutable GHCR image tag
just app-promote-prod app=dspace tag="$APP_TAG"
```

Current compatibility wrapper:

```bash
APP_TAG=main-REPLACE_SHORTSHA # replace with the staging-approved immutable GHCR image tag
just dspace-oci-promote-prod tag="$APP_TAG"
```

If `docs/apps/dspace.prod.tag` already contains the approved production tag, the
generic promotion command can read it by omitting `tag=`.

```bash
just app-promote-prod app=dspace
```

## 8. Verify production

```bash
just app-status app=dspace env=prod
```

```bash
just app-verify app=dspace env=prod
```

```bash
curl -fsS https://democratized.space/config.json | jq .
```

```bash
curl -fsS https://democratized.space/healthz
```

```bash
curl -fsS https://democratized.space/livez
```

## 9. Rollback

Rollback by immutable tag with the generic redeploy helper:

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA # replace with the previous known-good immutable GHCR image tag
just app-redeploy app=dspace env=prod tag="$APP_TAG"
```

Rollback staging the same way if the failure is caught before promotion:

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA # replace with the previous known-good immutable GHCR image tag
just app-redeploy app=dspace env=staging tag="$APP_TAG"
```

Rollback by Helm revision when a revision number is known:

```bash
DSPACE_REVISION=12 # replace with the known-good Helm revision
just tokenplace-rollback release=dspace namespace=dspace revision="$DSPACE_REVISION"
```

## 10. Troubleshooting

GHCR authentication and chart pull failures commonly show up as Helm `401` or
`403` errors. Log in to GHCR with a package-read credential, then retry the
chart check.

```bash
CHART_VERSION=$(grep -E '^[0-9]+\.[0-9]+\.[0-9]+' docs/apps/dspace.version | head -n1)
helm show chart oci://ghcr.io/democratizedspace/charts/dspace --version "$CHART_VERSION"
```

Inspect status, logs, ingress, and tunnel routing:

```bash
just app-status app=dspace env=staging
```

```bash
just dspace-debug-logs-env env=staging
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
just cf-tunnel-route host=staging.democratized.space
```

Low-level Helm OCI helpers remain available when you need to debug the generic
app wrapper. Prefer `just app-deploy app=dspace ...` for routine releases.

```bash
APP_TAG=main-REPLACE_SHORTSHA # replace with the immutable GHCR image tag from dspace CI
just helm-oci-install release=dspace namespace=dspace chart=oci://ghcr.io/democratizedspace/charts/dspace values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml version_file=docs/apps/dspace.version tag="$APP_TAG"
```

```bash
APP_TAG=main-REPLACE_SHORTSHA # replace with the immutable GHCR image tag from dspace CI
just helm-oci-upgrade release=dspace namespace=dspace chart=oci://ghcr.io/democratizedspace/charts/dspace values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml version_file=docs/apps/dspace.version tag="$APP_TAG"
```

## 11. App-specific notes

- dspace exposes `/config.json`, `/healthz`, and `/livez`; verify all three
  before promotion.
- `dspace-oci-deploy-prod-subdomain` remains available only for the optional
  `prod.democratized.space` legacy endpoint. Prefer the generic `prod` app flow
  for normal apex production releases.
- Keep mutable tags such as `latest` out of production. Use immutable branch-SHA
  or release tags for staging sign-off, production promotion, and rollback.
