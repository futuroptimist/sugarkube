# democratized.space (dspace) on Sugarkube

This runbook is the GHCR-first, generic-app deployment path for `dspace`. The app
repository owns image and chart publishing; Sugarkube owns kubeconfig selection,
values overlays, Helm deploys, status, verification, rollback, and logs. Cloudflare
Tunnel/DNS routes are configured outside Helm and must already point the public
hostnames at Traefik before production cutover.

App-specific `just` recipes remain documented as compatibility shims. Prefer the
generic `just app-* app=dspace` commands for new releases and future app
onboarding; the wrappers are scheduled for later removal only after the generic
flow has been exercised across routine releases.

For the shared contract, tag policy, and config lookup order, see
[Sugarkube app deployment contract](../app_deployment_contract.md). For future
apps, see [App onboarding](../app_onboarding.md).

## Artifact model

- App repository: `democratizedspace/dspace`
- Image: `ghcr.io/democratizedspace/dspace`
- Chart: `oci://ghcr.io/democratizedspace/charts/dspace`
- Helm release: `dspace`
- Kubernetes namespace: `dspace`
- Sugarkube app config: `docs/examples/apps/dspace.env`
- Chart version pin: `docs/apps/dspace.version`
- Production image tag pin: `docs/apps/dspace.prod.tag`
- Verify paths: `/config.json,/healthz,/livez`
- Optional production subdomain overlay: `docs/examples/dspace.values.prod-subdomain.yaml` for `prod.democratized.space`.

Responsibilities stay split:

- **App repo:** build the container image, publish immutable GHCR tags such as
  `main-REPLACE_SHORTSHA`, package the Helm chart, and publish immutable OCI chart
  versions.
- **Sugarkube:** select `dev`, `staging`, or `prod`; load app config; apply values
  overlays; run Helm; verify URLs; inspect pods/logs; and perform rollback.
- **Cloudflare:** maintain DNS and tunnel routes to Traefik. Helm creates
  Kubernetes Ingress objects, not Cloudflare routes.

## Environment topology

- Staging environment: `env=staging`, host `https://staging.democratized.space`.
- Production environment: `env=prod`, host `https://democratized.space`.
- Values overlays:
  - Base/dev: `docs/examples/dspace.values.dev.yaml`
  - Staging: `docs/examples/dspace.values.staging.yaml`
  - Production: `docs/examples/dspace.values.prod.yaml`

Current target topology is HA staging on `sugarkube3`/`sugarkube4`/`sugarkube5`, HA production on `sugarkube0`/`sugarkube1`/`sugarkube2`, and a planned single-node dev environment on `sugarkube6`.

Confirm Cloudflare routing separately when a hostname is new or has changed:

```bash
just cf-tunnel-route host=staging.democratized.space
```

```bash
just cf-tunnel-route host=democratized.space
```

## Find or publish GHCR image

Start from the app repository's image workflow. A successful workflow should push
an immutable tag, usually `main-REPLACE_SHORTSHA`, plus any app-specific release
or convenience tags documented by that repository.

```bash
gh run list --repo democratizedspace/dspace --workflow ci-image.yml --limit 10
```

Set the immutable image tag you are about to deploy:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

Inspect the GHCR image manifest before deploying. If this fails with an auth
error, login with a GitHub token that can read packages for the app repository.

```bash
docker manifest inspect ghcr.io/democratizedspace/dspace:$APP_TAG
```

Do not lead staging or production deployments with local Docker builds. Local
builds are for app-repo development only; Sugarkube deploys published GHCR
artifacts.

## Confirm/publish OCI chart

The app repository owns chart changes and immutable chart publishing. If the chart
changed, bump the chart version in the app repository before publishing; do not
republish different chart content at the same version.

Read the Sugarkube chart version pin:

```bash
APP_CHART_VERSION=$(grep -E '^[0-9]+[.][0-9]+[.][0-9]+' docs/apps/dspace.version | head -n1)
```

Confirm the pinned chart is available from GHCR:

```bash
helm show chart oci://ghcr.io/democratizedspace/charts/dspace --version "$APP_CHART_VERSION"
```

If the chart was changed but the pinned version is missing or stale, publish it
from the app repository first, then update `docs/apps/dspace.version` in Sugarkube only
after the immutable OCI chart exists.

## Deploy staging

Preferred generic command:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just app-deploy app=dspace env=staging tag="$APP_TAG"
```

Compatibility wrapper, kept for existing operators and scripts:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just dspace-oci-deploy env=staging tag="$APP_TAG"
```

Use `app-redeploy` only when you intentionally need the upgrade-only path for an
existing release and tag:

```bash
just app-redeploy app=dspace env=staging tag="$APP_TAG"
```

Low-level Helm OCI helpers remain available for unusual recovery work, but they
are no longer the preferred runbook path:

```bash
just helm-oci-install release=dspace namespace=dspace chart=oci://ghcr.io/democratizedspace/charts/dspace values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml version_file=docs/apps/dspace.version tag="$APP_TAG"
```

```bash
just helm-oci-upgrade release=dspace namespace=dspace chart=oci://ghcr.io/democratizedspace/charts/dspace values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml version_file=docs/apps/dspace.version tag="$APP_TAG"
```

## Verify staging

Use the generic verifier first. It resolves the host from the Helm release values
and curls the app config's verify paths.

```bash
just app-status app=dspace env=staging
```

```bash
just app-verify app=dspace env=staging
```

Manual staging checks:

```bash
kubectl --context sugar-staging -n dspace get deploy,po,svc,ingress
```

```bash
kubectl --context sugar-staging -n dspace rollout status deploy/dspace --timeout=180s
```

```bash
curl -fsS https://staging.democratized.space/config.json
curl -fsS https://staging.democratized.space/healthz
curl -fsS https://staging.democratized.space/livez
```

## Promote production

Promote only the exact immutable image tag that passed staging. If `tag=` is
omitted, the generic production command reads `docs/apps/dspace.prod.tag`; update that pin
only as an explicit approval step.

Preferred generic command:

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

## Verify production

```bash
just app-status app=dspace env=prod
```

```bash
just app-verify app=dspace env=prod
```

Manual production checks:

```bash
kubectl --context sugar-prod -n dspace get deploy,po,svc,ingress
```

```bash
kubectl --context sugar-prod -n dspace rollout status deploy/dspace --timeout=180s
```

```bash
curl -fsS https://democratized.space/config.json
curl -fsS https://democratized.space/healthz
curl -fsS https://democratized.space/livez
```

## Rollback

Rollback by redeploying the previous known-good immutable tag. Prefer this when
the previous image tag is known and the chart version did not need to change.

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA
```

```bash
just app-deploy app=dspace env=staging tag="$APP_TAG"
```

```bash
just app-promote-prod app=dspace tag="$APP_TAG"
```

Rollback by Helm revision only when you have confirmed the revision number:

```bash
APP_REVISION=12
```

```bash
just tokenplace-rollback release=dspace namespace=dspace revision="$APP_REVISION"
```

`tokenplace-rollback` is the repository's existing parameterized Helm rollback
helper despite its token.place-oriented name.

## Troubleshooting

GHCR/OCI auth failures usually mean Helm or Docker cannot read the package. Login
with a GitHub token that has package read access, then retry the chart/image
inspection commands.

```bash
helm registry login ghcr.io
```

```bash
helm show chart oci://ghcr.io/democratizedspace/charts/dspace --version "$APP_CHART_VERSION"
```

Inspect resolved config and cluster state:

```bash
just app-config app=dspace env=staging
```

```bash
just app-status app=dspace env=staging
```

```bash
kubectl --context sugar-staging -n dspace logs deploy/dspace --tail=120
```

Ingress and tunnel checks:

```bash
just traefik-status
```

```bash
just cf-tunnel-debug
```

## App-specific notes

- DSPACE uses `/config.json`, `/healthz`, and `/livez` as smoke checks.
- Keep release lineage separate from environment routing: immutable image tags choose the app version; values overlays choose staging vs production hosts.
- The optional `prod.democratized.space` overlay is not part of the default promotion path; use it only for an explicit pre-apex validation need.
