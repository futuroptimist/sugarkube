# danielsmith.io on Sugarkube

This runbook is the GHCR-first, generic-app deployment path for `danielsmith`. The app
repository owns image and chart publishing; Sugarkube owns kubeconfig selection,
values overlays, Helm deploys, status, verification, rollback, and logs. Cloudflare
Tunnel/DNS routes are configured outside Helm and must already point the public
hostnames at Traefik before production cutover.

App-specific `just` recipes remain documented as compatibility shims. Prefer the
generic `just app-* app=danielsmith` commands for new releases and future app
onboarding; the wrappers are scheduled for later removal only after the generic
flow has been exercised across routine releases.

For the shared contract, tag policy, and config lookup order, see
[Sugarkube app deployment contract](../app_deployment_contract.md). For future
apps, see [App onboarding](../app_onboarding.md).

## Artifact model

- App repository: `futuroptimist/danielsmith.io`
- Image: `ghcr.io/futuroptimist/danielsmith.io`
- Chart: `oci://ghcr.io/futuroptimist/charts/danielsmith`
- Helm release: `danielsmith`
- Kubernetes namespace: `danielsmith`
- Sugarkube app config: `docs/examples/apps/danielsmith.env`
- Chart version pin: `docs/apps/danielsmith.version`
- Production image tag pin: `docs/apps/danielsmith.prod.tag`
- Verify paths: `/,/livez,/healthz`

Responsibilities stay split:

- **App repo:** build the container image, publish immutable GHCR tags such as
  `main-REPLACE_SHORTSHA`, package the Helm chart, and publish immutable OCI chart
  versions.
- **Sugarkube:** select `dev`, `staging`, or `prod`; load app config; apply values
  overlays; run Helm; verify URLs; inspect pods/logs; and perform rollback.
- **Cloudflare:** maintain DNS and tunnel routes to Traefik. Helm creates
  Kubernetes Ingress objects, not Cloudflare routes.

## Environment topology

- Staging environment: `env=staging`, host `https://staging.danielsmith.io`.
- Production environment: `env=prod`, host `https://danielsmith.io`.
- Values overlays:
  - Base/dev: `docs/examples/danielsmith.values.dev.yaml`
  - Staging: `docs/examples/danielsmith.values.staging.yaml`
  - Production: `docs/examples/danielsmith.values.prod.yaml`

Sugarkube runs only the static web container for this Vite + Three.js site. There is no in-cluster API, database, queue, GPU, compute node, or other stateful dependency in the current deployment model.

Confirm Cloudflare routing separately when a hostname is new or has changed:

```bash
just cf-tunnel-route host=staging.danielsmith.io
```

```bash
just cf-tunnel-route host=danielsmith.io
```

## Find or publish GHCR image

Start from the app repository's image workflow. A successful workflow should push
an immutable tag, usually `main-REPLACE_SHORTSHA`, plus any app-specific release
or convenience tags documented by that repository.

```bash
gh run list --repo futuroptimist/danielsmith.io --workflow ci-image.yml --limit 10
```

Set the immutable image tag you are about to deploy:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

Inspect the GHCR image manifest before deploying. If this fails with an auth
error, login with a GitHub token that can read packages for the app repository.

```bash
docker manifest inspect ghcr.io/futuroptimist/danielsmith.io:$APP_TAG
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
APP_CHART_VERSION=$(grep -E '^[0-9]+[.][0-9]+[.][0-9]+' docs/apps/danielsmith.version | head -n1)
```

Confirm the pinned chart is available from GHCR:

```bash
helm show chart oci://ghcr.io/futuroptimist/charts/danielsmith --version "$APP_CHART_VERSION"
```

If the chart was changed but the pinned version is missing or stale, publish it
from the app repository first, then update `docs/apps/danielsmith.version` in Sugarkube only
after the immutable OCI chart exists.

## Deploy staging

Preferred generic command:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just app-deploy app=danielsmith env=staging tag="$APP_TAG"
```

Compatibility wrapper, kept for existing operators and scripts:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just danielsmith-oci-deploy env=staging tag="$APP_TAG"
```

Use `app-redeploy` only when you intentionally need the upgrade-only path for an
existing release and tag:

```bash
just app-redeploy app=danielsmith env=staging tag="$APP_TAG"
```

## Verify staging

Use the generic verifier first. It resolves the host from the Helm release values
and curls the app config's verify paths.

```bash
just app-status app=danielsmith env=staging
```

```bash
just app-verify app=danielsmith env=staging
```

Manual staging checks:

```bash
kubectl --context sugar-staging -n danielsmith get deploy,po,svc,ingress
```

```bash
kubectl --context sugar-staging -n danielsmith rollout status deploy/danielsmith --timeout=180s
```

```bash
curl -fsS https://staging.danielsmith.io/
curl -fsS https://staging.danielsmith.io/livez
curl -fsS https://staging.danielsmith.io/healthz
```

## Promote production

Promote only the exact immutable image tag that passed staging. If `tag=` is
omitted, the generic production command reads `docs/apps/danielsmith.prod.tag`; update that pin
only as an explicit approval step.

Preferred generic command:

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

## Verify production

```bash
just app-status app=danielsmith env=prod
```

```bash
just app-verify app=danielsmith env=prod
```

Manual production checks:

```bash
kubectl --context sugar-prod -n danielsmith get deploy,po,svc,ingress
```

```bash
kubectl --context sugar-prod -n danielsmith rollout status deploy/danielsmith --timeout=180s
```

```bash
curl -fsS https://danielsmith.io/
curl -fsS https://danielsmith.io/livez
curl -fsS https://danielsmith.io/healthz
```

## Rollback

Rollback by redeploying the previous known-good immutable tag. Prefer this when
the previous image tag is known and the chart version did not need to change.

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA
```

```bash
just app-deploy app=danielsmith env=staging tag="$APP_TAG"
```

```bash
just app-promote-prod app=danielsmith tag="$APP_TAG"
```

Rollback by Helm revision only when you have confirmed the revision number:

```bash
APP_REVISION=12
```

```bash
just tokenplace-rollback release=danielsmith namespace=danielsmith revision="$APP_REVISION"
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
helm show chart oci://ghcr.io/futuroptimist/charts/danielsmith --version "$APP_CHART_VERSION"
```

Inspect resolved config and cluster state:

```bash
just app-config app=danielsmith env=staging
```

```bash
just app-status app=danielsmith env=staging
```

```bash
kubectl --context sugar-staging -n danielsmith logs deploy/danielsmith --tail=120
```

Ingress and tunnel checks:

```bash
just traefik-status
```

```bash
just cf-tunnel-debug
```

## App-specific notes

- Treat `/` as the user-facing smoke check and `/livez` plus `/healthz` as availability checks.
- Preserve the app repository static-site build pipeline; Sugarkube consumes the published image and chart only.
- Do not add backend, database, or compute-node assumptions to Sugarkube values unless the app repository introduces those services first.
