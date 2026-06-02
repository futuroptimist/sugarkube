# token.place on Sugarkube

This runbook is the GHCR-first, generic-app deployment path for `tokenplace`. The app
repository owns image and chart publishing; Sugarkube owns kubeconfig selection,
values overlays, Helm deploys, status, verification, rollback, and logs. Cloudflare
Tunnel/DNS routes are configured outside Helm and must already point the public
hostnames at Traefik before production cutover.

App-specific `just` recipes remain documented as compatibility shims. Prefer the
generic `just app-* app=tokenplace` commands for new releases and future app
onboarding; the wrappers are scheduled for later removal only after the generic
flow has been exercised across routine releases.

For the shared contract, tag policy, and config lookup order, see
[Sugarkube app deployment contract](../app_deployment_contract.md). For future
apps, see [App onboarding](../app_onboarding.md).

## Artifact model

- App repository: `futuroptimist/token.place`
- Image: `ghcr.io/futuroptimist/tokenplace-relay`
- Chart: `oci://ghcr.io/futuroptimist/charts/tokenplace`
- Helm release: `tokenplace`
- Kubernetes namespace: `tokenplace`
- Sugarkube app config: `docs/examples/apps/tokenplace.env`
- Chart version pin: `docs/apps/tokenplace.version`
- Production image tag pin: `docs/apps/tokenplace.prod.tag`
- Verify paths: `/,/livez,/healthz,/relay/diagnostics`

Responsibilities stay split:

- **App repo:** build the container image, publish immutable GHCR tags such as
  `main-REPLACE_SHORTSHA`, package the Helm chart, and publish immutable OCI chart
  versions.
- **Sugarkube:** select `dev`, `staging`, or `prod`; load app config; apply values
  overlays; run Helm; verify URLs; inspect pods/logs; and perform rollback.
- **Cloudflare:** maintain DNS and tunnel routes to Traefik. Helm creates
  Kubernetes Ingress objects, not Cloudflare routes.

## Environment topology

- Staging environment: `env=staging`, host `https://staging.token.place`.
- Production environment: `env=prod`, host `https://token.place`.
- Values overlays:
  - Base/dev: `docs/examples/tokenplace.values.dev.yaml`
  - Staging: `docs/examples/tokenplace.values.staging.yaml`
  - Production: `docs/examples/tokenplace.values.prod.yaml`

Sugarkube runs only the token.place relay service. `server.py`, desktop clients, GPUs, Macs, PCs, and other compute nodes remain external. The current relay runtime is single replica, single worker, and in-memory; pod restarts can lose relay state and that is accepted for now.

Confirm Cloudflare routing separately when a hostname is new or has changed:

```bash
just cf-tunnel-route host=staging.token.place
```

```bash
just cf-tunnel-route host=token.place
```

## Find or publish GHCR image

Start from the app repository's image workflow. A successful workflow should push
an immutable tag, usually `main-REPLACE_SHORTSHA`, plus any app-specific release
or convenience tags documented by that repository.

```bash
gh run list --repo futuroptimist/token.place --workflow ci-image.yml --limit 10
```

Set the immutable image tag you are about to deploy:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

Inspect the GHCR image manifest before deploying. If this fails with an auth
error, login with a GitHub token that can read packages for the app repository.

```bash
docker manifest inspect ghcr.io/futuroptimist/tokenplace-relay:$APP_TAG
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
APP_CHART_VERSION=$(grep -E '^[0-9]+[.][0-9]+[.][0-9]+' docs/apps/tokenplace.version | head -n1)
```

Confirm the pinned chart is available from GHCR:

```bash
helm show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version "$APP_CHART_VERSION"
```

If the chart was changed but the pinned version is missing or stale, publish it
from the app repository first, then update `docs/apps/tokenplace.version` in Sugarkube only
after the immutable OCI chart exists.

## Deploy staging

Preferred generic command:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just app-deploy app=tokenplace env=staging tag="$APP_TAG"
```

Compatibility wrapper, kept for existing operators and scripts:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just tokenplace-oci-deploy env=staging tag="$APP_TAG"
```

Use `app-redeploy` only when you intentionally need the upgrade-only path for an
existing release and tag:

```bash
just app-redeploy app=tokenplace env=staging tag="$APP_TAG"
```

## Verify staging

Use the generic verifier first. It resolves the host from the Helm release values
and curls the app config's verify paths.

```bash
just app-status app=tokenplace env=staging
```

```bash
just app-verify app=tokenplace env=staging
```

Manual staging checks:

```bash
kubectl --context sugar-staging -n tokenplace get deploy,po,svc,ingress
```

```bash
kubectl --context sugar-staging -n tokenplace rollout status deploy/tokenplace --timeout=180s
```

```bash
curl -fsS https://staging.token.place/
curl -fsS https://staging.token.place/livez
curl -fsS https://staging.token.place/healthz
curl -fsS https://staging.token.place/relay/diagnostics
```

## Promote production

Promote only the exact immutable image tag that passed staging. If `tag=` is
omitted, the generic production command reads `docs/apps/tokenplace.prod.tag`; update that pin
only as an explicit approval step.

Preferred generic command:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just app-promote-prod app=tokenplace tag="$APP_TAG"
```

Compatibility wrapper:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

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

Manual production checks:

```bash
kubectl --context sugar-prod -n tokenplace get deploy,po,svc,ingress
```

```bash
kubectl --context sugar-prod -n tokenplace rollout status deploy/tokenplace --timeout=180s
```

```bash
curl -fsS https://token.place/
curl -fsS https://token.place/livez
curl -fsS https://token.place/healthz
curl -fsS https://token.place/relay/diagnostics
```

## Rollback

Rollback by redeploying the previous known-good immutable tag. Prefer this when
the previous image tag is known and the chart version did not need to change.

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA
```

```bash
just app-deploy app=tokenplace env=staging tag="$APP_TAG"
```

```bash
just app-promote-prod app=tokenplace tag="$APP_TAG"
```

Rollback by Helm revision only when you have confirmed the revision number:

```bash
APP_REVISION=12
```

```bash
just tokenplace-rollback release=tokenplace namespace=tokenplace revision="$APP_REVISION"
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
helm show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version "$APP_CHART_VERSION"
```

Inspect resolved config and cluster state:

```bash
just app-config app=tokenplace env=staging
```

```bash
just app-status app=tokenplace env=staging
```

```bash
kubectl --context sugar-staging -n tokenplace logs deploy/tokenplace --tail=120
```

Ingress and tunnel checks:

```bash
just traefik-status
```

```bash
just cf-tunnel-debug
```

## App-specific notes

- Web/TLS health is not complete relay validation. Before production, also run API v1 register/poll, confirm an external compute node registration, and complete an E2EE request/response through the relay.
- Avoid long-running public `/healthz` watches until token.place confirms health, liveness, metrics, diagnostics, and compute-node heartbeat routes are exempt from public API rate limits.
- Keep writable XDG `/tmp` defaults and duplicate-env prevention in the app chart, not as one-off Sugarkube CLI overrides.
- Related relay-focused guide: [`docs/apps/tokenplace-relay.md`](./tokenplace-relay.md).
