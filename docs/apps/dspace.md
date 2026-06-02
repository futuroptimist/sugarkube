# democratized.space (DSPACE) on Sugarkube

Use this runbook for GHCR-first DSPACE deploys from published GitHub Actions artifacts to
Sugarkube. The generic app recipes are the preferred future path; the `dspace-*` recipes are
compatibility shims that stay documented until the generic flow has been exercised across routine
releases.

## 1. Artifact model

App repo responsibilities:

- Build and publish the application image to GHCR from the DSPACE repository.
- Build and publish the Helm chart as an OCI artifact from the DSPACE repository.
- Keep image tags immutable for release validation, promotion, and rollback.

Sugarkube responsibilities:

- Select the kubeconfig/environment.
- Read the app config from `docs/examples/apps/dspace.env` or a copied local `apps/dspace.env`.
- Run Helm deploys with the configured values overlays and chart version pin.
- Verify Kubernetes rollout state, public HTTPS paths, status, and logs.

Cloudflare responsibilities:

- DNS and Cloudflare Tunnel routes are configured outside Helm.
- Route DSPACE hostnames to Traefik before expecting public HTTPS verification to pass.

Current artifact contract:

| Field | Value |
| --- | --- |
| Image | `ghcr.io/democratizedspace/dspace` |
| Chart | `oci://ghcr.io/democratizedspace/charts/dspace` |
| Release | `dspace` |
| Namespace | `dspace` |
| App config | `docs/examples/apps/dspace.env` |
| Chart version pin | `docs/apps/dspace.version` |
| Production tag pin | `docs/apps/dspace.prod.tag` |
| Verify paths | `/config.json`, `/healthz`, `/livez` |

## 2. Environment topology

Values overlays decide routing; image tags decide the app build. Keep those concerns separate.

| Environment | Sugarkube values chain | Public host |
| --- | --- | --- |
| `dev` | `docs/examples/dspace.values.dev.yaml` | Local/dev only unless overridden |
| `staging` | `docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml` | `staging.democratized.space` |
| `prod` | `docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.prod.yaml` | `democratized.space` |

Optional production-preview routing exists at `prod.democratized.space` via
`docs/examples/dspace.values.prod-subdomain.yaml`, but it is not part of the generic app config.
Use it only when intentionally validating that legacy preview endpoint.

## 3. Find or publish GHCR image

Find the successful image workflow run in the DSPACE app repo, then copy its immutable tag. Prefer
branch-SHA tags such as `main-REPLACE_SHORTSHA` or semver release tags. Do not deploy mutable tags
such as `latest`, `main`, `staging`, or `prod` through the generic recipes.

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
CHART_VERSION=$(sed -e 's/#.*$//' -e '/^[[:space:]]*$/d' docs/apps/dspace.version | head -n1)
```

```bash
helm show chart oci://ghcr.io/democratizedspace/charts/dspace --version "$CHART_VERSION"
```

If the chart changed in the DSPACE app repo, publish a new immutable OCI chart there first and then
update `docs/apps/dspace.version` in Sugarkube. If only the image changed, keep the chart version
pin unchanged.

## 5. Deploy staging

Preferred generic deploy:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just app-deploy app=dspace env=staging tag="$APP_TAG"
```

Compatibility wrapper while the generic flow bakes in:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just dspace-oci-deploy env=staging tag="$APP_TAG"
```

Lowest-level Helm helper examples remain available for debugging the wrappers, but they are not the
preferred operator path:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just helm-oci-install release=dspace namespace=dspace chart=oci://ghcr.io/democratizedspace/charts/dspace values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml version_file=docs/apps/dspace.version tag="$APP_TAG"
```

```bash
just helm-oci-upgrade release=dspace namespace=dspace chart=oci://ghcr.io/democratizedspace/charts/dspace values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml version_file=docs/apps/dspace.version tag="$APP_TAG"
```

## 6. Verify staging

Generic HTTPS smoke checks from the app config:

```bash
just app-verify app=dspace env=staging
```

Kubernetes status with the generic app config:

```bash
just app-status app=dspace env=staging
```

Compatibility status/log helpers:

```bash
just app-status namespace=dspace release=dspace
```

```bash
just dspace-debug-logs-env env=staging
```

Manual public checks when you need the exact commands:

```bash
curl -fsS https://staging.democratized.space/config.json | jq .
```

```bash
curl -fsS https://staging.democratized.space/healthz | jq .
```

```bash
curl -fsS https://staging.democratized.space/livez | jq .
```

## 7. Promote production

Promote only the exact immutable tag that passed staging.

Preferred generic production promotion:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just app-promote-prod app=dspace tag="$APP_TAG"
```

Compatibility wrapper:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just dspace-oci-promote-prod tag="$APP_TAG"
```

If `docs/apps/dspace.prod.tag` has already been reviewed and pinned to the approved tag, both
production promotion recipes can read it when `tag=` is omitted. Passing `tag=` is still clearer for
copy-pasteable release notes.

## 8. Verify production

Generic HTTPS smoke checks:

```bash
just app-verify app=dspace env=prod
```

Generic status:

```bash
just app-status app=dspace env=prod
```

Manual public checks:

```bash
curl -fsS https://democratized.space/config.json | jq .
```

```bash
curl -fsS https://democratized.space/healthz | jq .
```

```bash
curl -fsS https://democratized.space/livez | jq .
```

## 9. Rollback

Prefer immutable-tag rollback when the bad release maps to a single image tag:

```bash
PREVIOUS_TAG=main-REPLACE_PREVIOUS_SHORTSHA
```

```bash
just app-deploy app=dspace env=prod tag="$PREVIOUS_TAG"
```

Use Helm revision rollback when you must restore the full rendered release state:

```bash
HELM_REVISION=12
```

```bash
just tokenplace-rollback release=dspace namespace=dspace revision="$HELM_REVISION"
```

`tokenplace-rollback` is a generic parameterized Helm rollback helper despite its legacy name.

## 10. Troubleshooting

GHCR auth failures usually look like `401`, `403`, or `denied`. Log in and retry the chart check:

```bash
helm registry login ghcr.io -u "$GHCR_USER"
```

```bash
helm show chart oci://ghcr.io/democratizedspace/charts/dspace --version "$CHART_VERSION"
```

Check rendered app config before deploying:

```bash
just app-config app=dspace env=staging
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
just cf-tunnel-route host=staging.democratized.space
```

```bash
just cf-tunnel-route host=democratized.space
```

## 11. App-specific notes

- DSPACE keeps a mature release flow in its own repository; Sugarkube consumes the published image
  and chart instead of rebuilding locally.
- `dspace-oci-deploy-prod-subdomain` remains available for the optional
  `prod.democratized.space` preview endpoint and is intentionally separate from the generic
  `env=prod` apex promotion path.
- Staging is the required sign-off environment before promoting `democratized.space`.
