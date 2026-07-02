# Sugarkube future-app onboarding guide

Use this checklist when onboarding the next GHCR-first app to Sugarkube. The goal is that `wove` and later apps can reuse the same app repository release contract and the same Sugarkube `just app-*` operations without asking for bespoke deployment instructions.

## Ownership boundaries

- App repositories own build and release artifacts: `Dockerfile`, image workflow, Helm chart, chart workflow, chart version bumps, app defaults, and release notes.
- Sugarkube owns cluster operations: app config, kubeconfig/environment selection, values overlays, Helm deploy/redeploy/promote commands, status, verification, and logs.
- Cloudflare owns public routing outside Helm: DNS records, Tunnel hostname routes to Traefik, and any dashboard/API changes needed before public checks pass.

## New app onboarding checklist

1. Add a production Dockerfile in the app repository.
2. Add `ci-image.yml` with standard GHCR tags.
3. Add a Helm chart in the app repository.
4. Add `ci-helm.yml` with immutable OCI chart publishing.
5. Add or copy a Sugarkube app config.
6. Add environment values overlays for `dev`, `staging`, and `prod`.
7. Add a Sugarkube runbook with direct artifact discovery links for the app
   repo, image workflow, GHCR image package, chart workflow, GHCR chart package,
   Dockerfile/source image path, chart source path, and app-repo release guide
   when present.
8. Run the generic Sugarkube deploy.
9. Add app-specific smoke checks when generic HTTP checks are not enough.

## Minimal app config template

Keep private or local operator app config outside the repository. Set `SUGARKUBE_APP_CONFIG_DIR` to an operator-owned directory (for example `../sugarkube-app-config`) and write `APP.env` there, or pass an explicit `config=` path to every generic app command. Only sanitized, non-secret examples belong under `docs/examples/apps/APP.env`. Do not store secrets in either location.

```bash
export SUGARKUBE_APP_CONFIG_DIR=../sugarkube-app-config
mkdir -p "$SUGARKUBE_APP_CONFIG_DIR"
APP_CONFIG="$SUGARKUBE_APP_CONFIG_DIR/appslug.env"
cat >"$APP_CONFIG" <<'EOF'
SUGARKUBE_APP=appslug
SUGARKUBE_RELEASE=appslug
SUGARKUBE_NAMESPACE=appslug
SUGARKUBE_CHART=oci://ghcr.io/OWNER/charts/CHART
SUGARKUBE_VERSION_FILE=docs/apps/appslug.version
SUGARKUBE_PROD_TAG_FILE=docs/apps/appslug.prod.tag
SUGARKUBE_VALUES_DEV=docs/examples/appslug.values.dev.yaml
SUGARKUBE_VALUES_STAGING=docs/examples/appslug.values.dev.yaml,docs/examples/appslug.values.staging.yaml
SUGARKUBE_VALUES_PROD=docs/examples/appslug.values.dev.yaml,docs/examples/appslug.values.prod.yaml
SUGARKUBE_STATUS_HOST_KEY=ingress.host
SUGARKUBE_VERIFY_PATHS=/healthz,/livez
SUGARKUBE_DEBUG_SELECTOR=app.kubernetes.io/name=appslug
EOF
```

Check the resolved config before the first deploy.

```bash
just app-config app=appslug env=staging config="$APP_CONFIG"
```

Deploy staging with an immutable image tag.

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just app-deploy app=appslug env=staging tag="$APP_TAG" config="$APP_CONFIG"
```

## Minimal image workflow checklist

The app repo's `ci-image.yml` should answer yes to each item before Sugarkube starts using it.

- It builds from the production Dockerfile used by the Helm chart.
- It logs in to GHCR with repository-scoped credentials.
- It publishes `ghcr.io/OWNER/IMAGE`.
- It emits immutable branch-SHA tags such as `main-REPLACE_SHORTSHA`.
- It may emit convenience tags such as `main-latest`, but those are non-prod only unless an app runbook explicitly says otherwise.
- It does not require local Docker builds for staging or production deploys.
- It records enough workflow output for an operator to find the tag to deploy.

## Minimal Helm chart checklist

The app repo's chart and `ci-helm.yml` should answer yes to each item before Sugarkube pins a version.

- The chart sets `image.repository` and accepts `image.tag` overrides.
- The chart has values for ingress host, TLS, resources, environment, and health probes as needed.
- Chart changes bump `Chart.yaml` `version`.
- Application releases update `appVersion` when useful for humans, but chart content changes still require a chart `version` bump.
- `ci-helm.yml` publishes `oci://ghcr.io/OWNER/charts/CHART`.
- Published chart versions are immutable; never republish different content under an existing version.
- Sugarkube pins the deployed chart version in `docs/apps/APP.version`.
  Image tags and chart versions are separate coordinates: `just app-deploy tag=...`
  does not bump or auto-select charts.

## Environment overlay checklist

Create a base values file plus one overlay per environment.

- `docs/examples/APP.values.dev.yaml`: shared defaults and resource requests/limits.
- `docs/examples/APP.values.staging.yaml`: staging host, TLS secret, staging env vars, and staging-only settings.
- `docs/examples/APP.values.prod.yaml`: production host, TLS secret, production env vars, and production-only settings.
- Secrets must be referenced through Kubernetes Secret names or external secret tooling; never place secret values in docs or app configs.

## Questions before onboarding future apps

Do not invent real configs for future apps such as `wove` until their app repos have the required image and chart details. jobbot3000 is now onboarded because its image and chart details are known. Capture these answers first:

| Question | Why Sugarkube needs it |
| --- | --- |
| App repo URL | Anchors the runbook, source links, and release-guide link. |
| Image workflow URL | Lets operators find recent builds without searching GitHub Actions. |
| GHCR image package URL | Lets operators cross-check published image tags. |
| App image name | Sets `image.repository` and lets operators find GHCR image tags. |
| Container port | Drives Service and probe wiring in the chart. |
| Health endpoints | Sets `SUGARKUBE_VERIFY_PATHS` and Kubernetes probes. |
| Chart workflow URL | Lets operators find recent chart publish attempts. |
| GHCR chart package URL | Lets operators confirm immutable chart versions before pinning. |
| Dockerfile/source image path URL | Lets operators review the build context or source image before trusting published tags. |
| Chart source URL | Lets operators compare the published chart version with the source chart. |
| App-repo release guide URL, when present | Gives operators app-owned release notes and publish steps without searching the app repo. |
| Chart name | Sets the OCI chart reference. |
| Namespace and release | Sets stable Helm/Kubernetes ownership. |
| Staging and production hostnames | Drives values overlays, ingress, certs, and Cloudflare routes. |
| Runtime secrets/config | Determines Secret references and what must remain outside docs. |
| Stateful dependencies | Identifies databases, queues, volumes, migrations, backups, and rollback limits. |
| Resource requests/limits | Keeps scheduling predictable on Raspberry Pi clusters. |

## Release decision tree

### I have a successful image build; what tag do I deploy?

- Use the immutable branch-SHA or release tag from the successful image workflow.
- Prefer tags shaped like `main-REPLACE_SHORTSHA` for staging validation.
- Do not deploy `latest`, a bare branch name, or an environment name.
- Deploy staging first.

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just app-deploy app=appslug env=staging tag="$APP_TAG" config="$APP_CONFIG"
```

Before deploying, inspect the current chart pin:

```bash
just app-chart-status app=appslug config="$APP_CONFIG"
```

### The chart changed; what version do I bump?

- Bump the app repo chart `version` for any chart content change.
- Update `appVersion` when the human-facing app version changed.
- Publish the new OCI chart once.
- Update Sugarkube's `docs/apps/APP.version` to the new chart version after
  publication with the explicit bump workflow, then commit that pin before or
  with release operations. Do not use `chart=latest` or silent chart
  auto-upgrades for production.

```bash
just app-chart-bump app=appslug version=0.1.3 config="$APP_CONFIG"
```

```bash
git add docs/apps/appslug.version
git commit -m "Bump appslug chart pin to 0.1.3"
```

### Staging works; how do I promote prod?

- Keep the same immutable image tag that passed staging.
- Record or review the approved tag in `docs/apps/APP.prod.tag` when the app uses a committed prod pin.
- Use the generic production promotion command.

```bash
just app-promote-prod app=appslug tag="$APP_TAG" config="$APP_CONFIG"
```

### Prod is bad; how do I roll back?

- Prefer rolling back by deploying the previous known-good immutable image tag.
- Use Helm revision rollback only when you intentionally want to return to a previous rendered release state.
- Remember that stateful dependencies can require app-specific recovery steps beyond Helm.

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA
```

```bash
just app-redeploy app=appslug env=prod tag="$APP_TAG" config="$APP_CONFIG"
```

```bash
HELM_REVISION=12
```

```bash
ROLLBACK_ENV=prod
just kubeconfig-env "$ROLLBACK_ENV"
```

```bash
just tokenplace-rollback release=appslug namespace=appslug revision="$HELM_REVISION"
```

## First-run smoke check pattern

Start with generic checks. `just app-verify` executes the configured paths, prints readable per-path output with body previews, and exits non-zero if any path fails.

```bash
just app-status app=appslug env=staging config="$APP_CONFIG"
```

```bash
just app-verify app=appslug env=staging config="$APP_CONFIG"
```

Use print-only mode when you need the generated curl commands without making requests:

```bash
just app-verify app=appslug env=staging config="$APP_CONFIG" print_only=1
```

Add app-specific checks only for behavior the generic URL checks cannot validate, such as a login-free API health endpoint, a static asset manifest, a queue worker heartbeat, or a safe diagnostics endpoint.
