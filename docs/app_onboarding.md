# Sugarkube future-app onboarding

Use this checklist to onboard the next apps, including **wove** and **jobbot3000**, without
inventing live hostnames, secrets, or production tags before their app repositories publish the
required details.

## Responsibility split

App repository responsibilities:

- Build and publish a container image to GHCR.
- Build and publish a Helm chart to GHCR as an immutable OCI artifact.
- Own app-specific tests, smoke checks, runtime config, and release notes.

Sugarkube responsibilities:

- Store app config and environment values overlays.
- Select kubeconfig and environment.
- Run generic Helm deploy, status, verify, logs, promotion, and rollback recipes.

Cloudflare responsibilities:

- DNS records and Cloudflare Tunnel routes are outside Helm.
- Route each staging/prod hostname to Traefik before public HTTPS verification.

## Onboarding checklist

1. Add a `Dockerfile` in the app repo.
2. Add `ci-image.yml` in the app repo with standard GHCR tags.
3. Add a Helm chart in the app repo.
4. Add `ci-helm.yml` in the app repo with immutable OCI chart publishing.
5. Add or copy a Sugarkube app config.
6. Add environment values overlays for `dev`, `staging`, and `prod`.
7. Run the generic Sugarkube deploy.
8. Add app-specific smoke checks if needed.

## Minimal app config template

Copy this to `apps/APP_SLUG.env` for private/local configs or to `docs/examples/apps/APP_SLUG.env`
when the example is safe to publish. Replace placeholder values with real app details after the app
repo has confirmed them.

```dotenv
SUGARKUBE_APP=APP_SLUG
SUGARKUBE_RELEASE=APP_SLUG
SUGARKUBE_NAMESPACE=APP_SLUG
SUGARKUBE_CHART=oci://ghcr.io/OWNER/charts/CHART_NAME
SUGARKUBE_VERSION_FILE=docs/apps/APP_SLUG.version
SUGARKUBE_PROD_TAG_FILE=docs/apps/APP_SLUG.prod.tag
SUGARKUBE_VALUES_DEV=docs/examples/APP_SLUG.values.dev.yaml
SUGARKUBE_VALUES_STAGING=docs/examples/APP_SLUG.values.dev.yaml,docs/examples/APP_SLUG.values.staging.yaml
SUGARKUBE_VALUES_PROD=docs/examples/APP_SLUG.values.dev.yaml,docs/examples/APP_SLUG.values.prod.yaml
SUGARKUBE_STATUS_HOST_KEY=ingress.host
SUGARKUBE_VERIFY_PATHS=/,/healthz,/livez
SUGARKUBE_DEBUG_SELECTOR=app.kubernetes.io/name=APP_SLUG
```

Create the chart version pin:

```bash
printf '0.1.0\n' > docs/apps/APP_SLUG.version
```

Create the production tag pin and leave it empty until a production tag is approved:

```bash
printf '# Approved production image tag for APP_SLUG.\n' > docs/apps/APP_SLUG.prod.tag
```

## Minimal image workflow checklist

The app repo image workflow should:

- Run on pushes to the default branch and release tags.
- Authenticate with `GITHUB_TOKEN` or an explicitly scoped GHCR token.
- Publish to `ghcr.io/OWNER/IMAGE_NAME`.
- Emit immutable branch-SHA tags such as `main-REPLACE_SHORTSHA`.
- Emit semver tags when building release tags such as `v0.1.0`.
- Avoid relying on `latest`, `main`, `staging`, or `prod` for Sugarkube deploys.
- Record the image digest in workflow output or release notes.

## Minimal Helm chart checklist

The app repo chart should:

- Include a stable `Chart.yaml` name and semver `version`.
- Set `appVersion` to the app release where practical.
- Expose values for image repository, image tag, ingress host, service port, probes, resources, and
  runtime config.
- Avoid hard-coding Sugarkube staging/prod hostnames in templates; put hostnames in values overlays.
- Publish to `oci://ghcr.io/OWNER/charts/CHART_NAME`.
- Require a chart version bump whenever templates, default values, or CRD assumptions change.

## Environment values overlays

Create one base/dev values file and one overlay per routable environment:

```bash
APP_SLUG=wove
```

```bash
cat > "docs/examples/${APP_SLUG}.values.dev.yaml" <<'YAML'
environment: dev
image:
  repository: ghcr.io/OWNER/IMAGE_NAME
ingress:
  enabled: true
  className: traefik
YAML
```

```bash
cat > "docs/examples/${APP_SLUG}.values.staging.yaml" <<'YAML'
environment: staging
ingress:
  enabled: true
  className: traefik
  host: staging.example.com
YAML
```

```bash
cat > "docs/examples/${APP_SLUG}.values.prod.yaml" <<'YAML'
environment: prod
ingress:
  enabled: true
  className: traefik
  host: example.com
YAML
```

The hostnames above are illustrative. Do not commit invented wove or jobbot3000 hostnames; replace
them only after the app owner confirms real staging and production routes.

## Generic deploy flow for a newly onboarded app

Inspect the resolved config:

```bash
just app-config app=APP_SLUG env=staging
```

Deploy the immutable image tag that the app repo published:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just app-deploy app=APP_SLUG env=staging tag="$APP_TAG"
```

Verify public HTTPS paths from `SUGARKUBE_VERIFY_PATHS`:

```bash
just app-verify app=APP_SLUG env=staging
```

Promote the exact staging-approved tag:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just app-promote-prod app=APP_SLUG tag="$APP_TAG"
```

Rollback by redeploying the previous immutable tag:

```bash
PREVIOUS_TAG=main-REPLACE_PREVIOUS_SHORTSHA
```

```bash
just app-deploy app=APP_SLUG env=prod tag="$PREVIOUS_TAG"
```

## Questions to answer for wove, jobbot3000, and later apps

Answer these before adding real Sugarkube configs:

- App image name: what exact `ghcr.io/OWNER/IMAGE_NAME` should Sugarkube deploy?
- Container port: which port does the Kubernetes Service target?
- Health endpoints: which paths should `just app-verify` call?
- Chart name: what exact `oci://ghcr.io/OWNER/charts/CHART_NAME` is published?
- Namespace/release: should the Kubernetes namespace and Helm release match the app slug?
- Staging/prod hostnames: which public hosts should Cloudflare route to Traefik?
- Runtime secrets/config: which settings are values, which are Kubernetes Secrets, and which are
  managed outside Sugarkube?
- Stateful dependencies: does the app need a database, queue, object store, persistent volume, or
  external service?
- Resource requests/limits: what CPU and memory are safe for the Pi cluster and production HA?

## Release decision tree

### I have a successful image build; what tag do I deploy?

Use the immutable branch-SHA tag from the app repo workflow, for example:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

If the workflow also produced a semver release tag and that release is the intended artifact, use
that semver tag. Never use `latest`, `main`, `staging`, or `prod` for generic Sugarkube deploys.

### The chart changed; what version do I bump?

Bump the chart `version` in the app repo whenever templates, default values, chart metadata, probe
configuration, or resource defaults changed. Publish the new OCI chart, then update the matching
Sugarkube pin file:

```bash
printf '0.1.1\n' > docs/apps/APP_SLUG.version
```

If only the application image changed, do not bump the chart version.

### Staging works; how do I promote prod?

Promote the exact immutable tag that passed staging:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just app-promote-prod app=APP_SLUG tag="$APP_TAG"
```

Optionally record the approved tag in `docs/apps/APP_SLUG.prod.tag` after review so future
production deploys can use the pinned fallback.

### Prod is bad; how do I roll back?

If the chart is still good and only the image is bad, redeploy the previous immutable image tag:

```bash
PREVIOUS_TAG=main-REPLACE_PREVIOUS_SHORTSHA
```

```bash
just app-deploy app=APP_SLUG env=prod tag="$PREVIOUS_TAG"
```

If rendered manifests, values, or chart behavior are bad, roll back the Helm revision:

```bash
HELM_REVISION=12
```

```bash
just tokenplace-rollback release=APP_SLUG namespace=APP_SLUG revision="$HELM_REVISION"
```

`tokenplace-rollback` is a generic parameterized Helm rollback helper despite its legacy name.
