# Sugarkube app onboarding guide

Use this guide when adding the next app to Sugarkube, including future candidates
such as **wove** and **jobbot3000**. The goal is a repeatable GHCR-first release
flow: the app repository publishes an immutable image and immutable OCI Helm
chart, then Sugarkube deploys those artifacts with generic `just app-*` recipes.

Keep responsibilities separate:

- **App repository responsibilities:** Dockerfile, image workflow, Helm chart,
  chart workflow, chart tests/render checks, and app-specific smoke-test design.
- **Sugarkube responsibilities:** app config, environment values overlays,
  kubeconfig/environment selection, Helm deploy/redeploy/promote/status/verify,
  Kubernetes logs, and rollback.
- **Cloudflare responsibilities:** DNS records and tunnel routes that point public
  hostnames to Traefik. Helm manages Kubernetes Ingress objects only; it does not
  create Cloudflare routes.

App-specific deploy recipes are compatibility shims for existing apps. Keep them
for now, but prefer generic commands in new app docs. Remove shims only after the
generic flow has been exercised across routine releases.

## Onboarding checklist

1. Add a Dockerfile in the app repository.
2. Add `ci-image.yml` in the app repository with standard GHCR tags.
3. Add a Helm chart in the app repository.
4. Add `ci-helm.yml` in the app repository with immutable OCI chart publishing.
5. Add or copy a Sugarkube app config file.
6. Add environment values overlays for `dev`, `staging`, and `prod`.
7. Run the generic Sugarkube deploy commands.
8. Add app-specific smoke checks if needed.

## Minimal app config template

Copy this into a local config such as `apps/APP.env`, or add an example under
`docs/examples/apps/APP.env` when the repository has enough real coordinates to
serve as an example. Do not store secrets in app configs.

```dotenv
SUGARKUBE_APP=APP
SUGARKUBE_RELEASE=APP
SUGARKUBE_NAMESPACE=APP
SUGARKUBE_CHART=oci://ghcr.io/OWNER/charts/CHART
SUGARKUBE_VERSION_FILE=docs/apps/APP.version
SUGARKUBE_PROD_TAG_FILE=docs/apps/APP.prod.tag
SUGARKUBE_VALUES_DEV=docs/examples/APP.values.dev.yaml
SUGARKUBE_VALUES_STAGING=docs/examples/APP.values.dev.yaml,docs/examples/APP.values.staging.yaml
SUGARKUBE_VALUES_PROD=docs/examples/APP.values.dev.yaml,docs/examples/APP.values.prod.yaml
SUGARKUBE_STATUS_HOST_KEY=ingress.host
SUGARKUBE_VERIFY_PATHS=/,/livez,/healthz
SUGARKUBE_DEBUG_SELECTOR=app.kubernetes.io/name=APP
```

Create the local config directory when using app configs that are not committed:

```bash
mkdir -p apps
```

```bash
cp docs/examples/apps/dspace.env apps/APP.env
```

```bash
export SUGARKUBE_APP_CONFIG_DIR=apps
```

Confirm Sugarkube can resolve the config:

```bash
just app-config app=APP env=staging
```

## Minimal image workflow checklist

The app repository's `ci-image.yml` should answer these questions before
Sugarkube deploys anything:

- Does the workflow build the canonical app image from the app repository's
  Dockerfile?
- Does it push to the agreed GHCR image name, for example
  `ghcr.io/OWNER/IMAGE`?
- Does every merge or release candidate produce an immutable tag such as
  `main-REPLACE_SHORTSHA`?
- Are mutable convenience tags, if any, documented as non-production shortcuts?
- Does the workflow publish architecture support that matches Sugarkube nodes?
- Does the workflow avoid requiring Sugarkube secrets? Sugarkube should read the
  published package, not build the image.

Find recent image builds from the app repository:

```bash
gh run list --repo OWNER/REPO --workflow ci-image.yml --limit 10
```

Set the candidate image tag for deployment:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

Confirm the image manifest exists:

```bash
docker manifest inspect ghcr.io/OWNER/IMAGE:$APP_TAG
```

## Minimal Helm chart checklist

The app repository's chart and `ci-helm.yml` should satisfy this before Sugarkube
pins a chart version:

- `Chart.yaml` has the intended chart name and a semantic chart version.
- Image repository/tag values are configurable by Helm values.
- Ingress host, class, TLS secret, annotations, resources, env, probes, and any
  app-specific runtime config are values-driven.
- Chart versions are immutable. If rendered manifests change, bump the chart
  version before publishing.
- The workflow packages and pushes to `oci://ghcr.io/OWNER/charts/CHART`.
- The app repository can render the chart for `dev`, `staging`, and `prod`
  overlays without duplicate env vars or missing required values.

Check the chart version that Sugarkube will deploy:

```bash
APP_CHART_VERSION=$(grep -E '^[0-9]+[.][0-9]+[.][0-9]+' docs/apps/APP.version | head -n1)
```

```bash
helm show chart oci://ghcr.io/OWNER/charts/CHART --version "$APP_CHART_VERSION"
```

## Environment values overlays

Use one base values file plus thin environment overlays:

- `docs/examples/APP.values.dev.yaml`: shared defaults and local/dev settings.
- `docs/examples/APP.values.staging.yaml`: staging host, TLS secret, and staging
  runtime config.
- `docs/examples/APP.values.prod.yaml`: production host, TLS secret, and
  production runtime config.

Keep secrets out of values examples. Reference Kubernetes Secret names or
external secret mechanisms rather than literal secret values.

## Generic Sugarkube deploy flow

Deploy staging:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just app-deploy app=APP env=staging tag="$APP_TAG"
```

Verify staging:

```bash
just app-status app=APP env=staging
```

```bash
just app-verify app=APP env=staging
```

Promote production after staging sign-off:

```bash
just app-promote-prod app=APP tag="$APP_TAG"
```

Verify production:

```bash
just app-status app=APP env=prod
```

```bash
just app-verify app=APP env=prod
```

Rollback to a previous immutable image tag:

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA
```

```bash
just app-promote-prod app=APP tag="$APP_TAG"
```

## Release decision tree

### I have a successful image build; what tag do I deploy?

Deploy the immutable tag emitted by the image workflow, normally
`main-REPLACE_SHORTSHA`. Do not deploy `latest`, a bare branch name, or an
environment name to staging or production. Use the same immutable tag through
staging verification and production promotion.

### The chart changed; what version do I bump?

Bump the chart version in the app repository whenever chart content changes.
Patch bumps are typical for template/default-value fixes, minor bumps are for
new chart capabilities, and major bumps are for breaking chart contract changes.
Publish the new immutable OCI chart first, then update the Sugarkube
`docs/apps/APP.version` pin.

### Staging works; how do I promote prod?

Promote the exact immutable image tag that passed staging:

```bash
just app-promote-prod app=APP tag="$APP_TAG"
```

Update `docs/apps/APP.prod.tag` only when the team explicitly approves that tag
as the production pin. When `tag=` is omitted, the generic production flow reads
that pin file.

### Prod is bad; how do I roll back?

If the previous known-good image tag is known, redeploy that immutable tag:

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA
```

```bash
just app-promote-prod app=APP tag="$APP_TAG"
```

If the image tag is unknown but a Helm revision is known, use the parameterized
rollback helper:

```bash
APP_REVISION=12
```

```bash
just tokenplace-rollback release=APP namespace=APP revision="$APP_REVISION"
```

## wove and jobbot3000 pre-onboarding questions

Do not invent Sugarkube configs for **wove** or **jobbot3000** until these
answers are available from their app repositories or owners:

- What is the canonical app image name?
- What container port does the service expose?
- Which health endpoints should Sugarkube verify?
- What is the chart name and OCI chart path?
- What Kubernetes namespace and Helm release name should be used?
- What are the staging and production hostnames?
- What runtime secrets and non-secret config are required?
- Are there stateful dependencies such as a database, queue, cache, object store,
  or persistent volume?
- What resource requests and limits are appropriate for Sugarkube hardware?

Once those answers are known, copy the template above, add the three values
overlays, publish image/chart artifacts from the app repository, and run the
generic Sugarkube deploy flow.
