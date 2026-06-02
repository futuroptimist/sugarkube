# Future app onboarding guide

Use this checklist when adding a new app to the Sugarkube generic app flow. The
next likely candidates are **wove** and **jobbot3000**, but do not add their real
Sugarkube configs until their app repositories have answered the questions below
and published compatible GHCR image/chart artifacts.

## Ownership boundary

- App repository responsibilities: Dockerfile, image workflow, Helm chart, chart
  workflow, app-specific smoke endpoints, and release tags.
- Sugarkube responsibilities: app config, environment values overlays,
  kubeconfig/environment selection, Helm deploy/redeploy/promote/status/verify,
  and cluster logs.
- Cloudflare responsibilities: DNS records and tunnel routes. Cloudflare routes
  are configured outside Helm and should not be hidden inside app values.

App-specific `just` recipes for dspace, token.place, and danielsmith.io are
compatibility shims. Keep documenting them during migration, but prefer generic
commands for new apps. Remove shims only after the generic flow has been used
successfully across routine releases.

## Onboarding checklist

1. Add a Dockerfile in the app repository.
2. Add `ci-image.yml` with standard GHCR tags.
3. Add a Helm chart in the app repository.
4. Add `ci-helm.yml` with immutable OCI chart publishing.
5. Add or copy a Sugarkube app config.
6. Add environment values overlays for dev, staging, and prod.
7. Run the generic Sugarkube deploy.
8. Add app-specific smoke checks if needed.

## Questions to answer before onboarding wove, jobbot3000, or another app

| Question | Why it matters |
| --- | --- |
| App image name | Determines the GHCR image coordinate and image override values. |
| Container port | Drives Service target ports and readiness/liveness probe wiring. |
| Health endpoints | Defines `SUGARKUBE_VERIFY_PATHS` and any app-specific smoke checks. |
| Chart name | Determines the OCI chart reference and chart version pin. |
| Namespace/release | Keeps Helm history and Kubernetes resources stable across releases. |
| Staging/prod hostnames | Drives ingress values and Cloudflare tunnel routes. |
| Runtime secrets/config | Identifies required Kubernetes Secrets and non-secret ConfigMap values. |
| Stateful dependencies | Determines whether a stateless deploy is enough or extra runbooks are needed. |
| Resource requests/limits | Keeps small Sugarkube clusters predictable under load. |

## Minimal app config template

Copy this template into a local config directory or `docs/examples/apps/APP.env`
when the app is ready. Replace `APP` and the GHCR coordinates with real values;
keep placeholder values out of production docs once the app is live.

```bash
SUGARKUBE_APP=APP
SUGARKUBE_RELEASE=APP
SUGARKUBE_NAMESPACE=APP
SUGARKUBE_CHART=oci://ghcr.io/OWNER/charts/APP
SUGARKUBE_VERSION_FILE=docs/apps/APP.version
SUGARKUBE_PROD_TAG_FILE=docs/apps/APP.prod.tag
SUGARKUBE_VALUES_DEV=docs/examples/APP.values.dev.yaml
SUGARKUBE_VALUES_STAGING=docs/examples/APP.values.dev.yaml,docs/examples/APP.values.staging.yaml
SUGARKUBE_VALUES_PROD=docs/examples/APP.values.dev.yaml,docs/examples/APP.values.prod.yaml
SUGARKUBE_STATUS_HOST_KEY=ingress.host
SUGARKUBE_VERIFY_PATHS=/,/healthz,/livez
SUGARKUBE_DEBUG_SELECTOR=app.kubernetes.io/name=APP
```

After adding a config, confirm Sugarkube can resolve it:

```bash
just app-config app=APP env=staging
```

## Minimal image workflow checklist

The app repository's image workflow should publish to GHCR and expose tags that
operators can copy directly into Sugarkube docs.

- Trigger on pushes to the integration branch and manual `workflow_dispatch`.
- Build the production image for `linux/amd64` and `linux/arm64` unless the app
  has a documented architecture exception.
- Publish the canonical image name only, for example `ghcr.io/OWNER/APP`.
- Publish immutable branch-SHA tags such as `main-REPLACE_SHORTSHA`.
- Optionally publish mutable convenience tags such as `main-latest` for
  non-production iteration, but do not use them for production promotion.
- Make the workflow summary print the image coordinate and immutable tag.
- Avoid requiring Sugarkube to run a local image build for staging or production.

## Minimal Helm chart checklist

The app repository's chart workflow should publish an immutable OCI chart that
Sugarkube can install with `helm upgrade --install`.

- Store the chart in the app repository near app release docs.
- Use a stable chart name that matches the planned Sugarkube app slug when
  possible.
- Expose image repository and tag values that Sugarkube can override.
- Include ingress host/class/TLS values for each environment overlay.
- Include readiness and liveness probes for the health endpoints.
- Keep secrets out of values files; reference Kubernetes Secrets by name instead.
- Bump chart patch versions for template/default changes, minor versions for
  backwards-compatible chart interface additions, and major versions for breaking
  values/schema changes.
- Publish to `oci://ghcr.io/OWNER/charts/CHART` from `ci-helm.yml`.

## Environment values overlays

Keep values files layered from broad defaults to environment-specific routing.

```bash
docs/examples/APP.values.dev.yaml
```

```bash
docs/examples/APP.values.staging.yaml
```

```bash
docs/examples/APP.values.prod.yaml
```

Typical split:

- Dev/base values: image defaults, service port, resource requests/limits,
  non-secret defaults, and shared probe paths.
- Staging overlay: staging hostname, ingress class/TLS settings, staging-specific
  non-secret config.
- Prod overlay: production hostname, ingress class/TLS settings, production
  non-secret config.

## Generic deploy smoke path

Deploy a staging candidate with the generic app flow:

```bash
APP_TAG=main-REPLACE_SHORTSHA # replace with the immutable GHCR image tag from the app CI
just app-deploy app=APP env=staging tag="$APP_TAG"
```

Verify staging:

```bash
just app-status app=APP env=staging
```

```bash
just app-verify app=APP env=staging
```

Promote after staging sign-off:

```bash
APP_TAG=main-REPLACE_SHORTSHA # replace with the staging-approved immutable GHCR image tag
just app-promote-prod app=APP tag="$APP_TAG"
```

Rollback production by tag:

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA # replace with the previous known-good immutable GHCR image tag
just app-redeploy app=APP env=prod tag="$APP_TAG"
```

## Release decision tree

### I have a successful image build; what tag do I deploy?

- If staging is the next step, deploy the immutable branch-SHA tag printed by CI,
  for example `main-REPLACE_SHORTSHA`.
- If CI only printed a mutable convenience tag, find the matching immutable tag
  before deploying.
- If the app has release tags, deploy the immutable release tag that corresponds
  to the signed-off source revision.

### The chart changed; what version do I bump?

- Patch version: chart template fixes, resource default tweaks, or probe changes
  that preserve the values interface.
- Minor version: new optional values, new optional templates, or backwards-
  compatible environment support.
- Major version: breaking values schema changes, renamed resources that affect
  upgrades, or migration steps that require operator action.
- After the chart is published, update the Sugarkube `docs/apps/APP.version` pin
  in the same docs/config PR that explains the deploy impact.

### Staging works; how do I promote prod?

- Promote the exact immutable tag that passed staging.
- Prefer `just app-promote-prod app=APP tag="$APP_TAG"` for the active release.
- Update `docs/apps/APP.prod.tag` when the repo should remember that approved tag
  for future no-argument production promotion.

### Prod is bad; how do I roll back?

- First choose the previous known-good immutable image tag from release notes,
  `docs/apps/APP.prod.tag` history, or Helm history.
- Run `just app-redeploy app=APP env=prod tag="$APP_TAG"` with that known-good
  tag.
- If image rollback is not enough, use the known-good Helm revision and the
  existing parameterized rollback helper.
- Verify production with `just app-status app=APP env=prod` and
  `just app-verify app=APP env=prod` before closing the incident.
