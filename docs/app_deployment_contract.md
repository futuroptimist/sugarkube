# Sugarkube app deployment contract

Sugarkube now exposes a generic app deployment surface where each app is
identified by a small local config file and deployed with shared `just` recipes.
This page is the contract that app repositories and local operator configs should
follow.

The existing app-specific recipes for dspace, token.place, and danielsmith.io
remain compatibility shims during migration. They are intentionally not removed
in this phase and will be deprecated only after downstream runbooks have moved to
the generic flow.

## Ownership boundary

App repositories own build and release artifacts:

- the application `Dockerfile`;
- the application Helm chart;
- GHCR image publishing; and
- GHCR Helm OCI chart publishing.

Sugarkube owns cluster and environment orchestration:

- choosing the environment (`dev`, `staging`, or `prod`);
- selecting the chart version pin;
- selecting the approved image tag;
- applying the environment values chain; and
- running status and verification checks against the cluster.

Future onboarding examples should only get Sugarkube app configs after their
app repositories have published compatible images and charts.
Use the [future-app onboarding guide](app_onboarding.md) for the checklist, minimal config template, and release decision tree.

## Standard artifact model

Each Sugarkube-managed app needs the following deployment coordinates:

| Coordinate | Contract |
| --- | --- |
| Image | `ghcr.io/OWNER/IMAGE` |
| Chart | `oci://ghcr.io/OWNER/charts/CHART` |
| Release name | Stable Helm release name, normally the app slug. |
| Namespace | Stable Kubernetes namespace, normally the app slug. |
| Chart version pin file | A repo file containing the chart version Sugarkube should install or upgrade. |
| Production tag pin file | Required repo file containing the production-approved immutable image tag for production promotion. |
| Values chain per env | Comma-separated Helm values files, ordered from base to environment overlay. |
| Validation URLs/paths | Host key plus one or more HTTP paths to check after rollout. |

### Artifact discovery links

Every app runbook must include required runbook links that make artifacts
discoverable without manually searching GitHub Actions or GHCR:

- the app repository;
- the image workflow;
- the GHCR image package;
- the chart workflow;
- the GHCR chart package;
- the Dockerfile or source image path;
- the chart source path; and
- the app-repo Sugarkube release guide when one is present.

The current apps map to that model as examples:

| App | Image | Chart | Release | Namespace | Version pin | Prod tag pin |
| --- | --- | --- | --- | --- | --- | --- |
| dspace | `ghcr.io/democratizedspace/dspace` | `oci://ghcr.io/democratizedspace/charts/dspace` | `dspace` | `dspace` | `docs/apps/dspace.version` | `docs/apps/dspace.prod.tag` |
| token.place | `ghcr.io/futuroptimist/tokenplace-relay` | `oci://ghcr.io/futuroptimist/charts/tokenplace` | `tokenplace` | `tokenplace` | `docs/apps/tokenplace.version` | `docs/apps/tokenplace.prod.tag` |
| danielsmith.io | `ghcr.io/futuroptimist/danielsmith.io` | `oci://ghcr.io/futuroptimist/charts/danielsmith` | `danielsmith` | `danielsmith` | `docs/apps/danielsmith.version` | `docs/apps/danielsmith.prod.tag` |
| jobbot3000 | `ghcr.io/futuroptimist/jobbot3000` | `oci://ghcr.io/futuroptimist/charts/jobbot3000` | `jobbot3000` | `jobbot3000` | `docs/apps/jobbot3000.version` | `docs/apps/jobbot3000.prod.tag` |

## Standard image tag model

Deployment tags must identify application code and release intent, not mutable
environments.

Acceptable deployment tags:

- Immutable branch-SHA tags, such as `main-REPLACE_SHORTSHA`.
- Semver or release tags, such as `v1.2.3`, `3.1.0`, or another documented
  project-specific stable tag.
- Mutable branch convenience tags, such as `main-latest`, only when an app
  runbook explicitly documents that a non-prod bootstrap or iteration flow accepts
  them. They are an app-specific exception, not a shared guarantee; for example,
  token.place deploy/redeploy wrappers reject every tag containing `latest`,
  including `main-latest`.

Unacceptable deployment tags:

- `latest`;
- bare branch names such as `main`, `master`, `develop`, or `release`; and
- environment names such as `dev`, `staging`, `prod`, or `production`.

Production promotion must use an immutable tag. The production tag pin file is
part of the standard app coordinates and must contain the single immutable image
tag approved for production. Generic production promotion flows should read that
pin when `tag=` is omitted and should update it only as an explicit approval
step.

## Standard chart publishing model

Helm charts are immutable once published to GHCR OCI:

- Chart versions are immutable and must not be republished with different
  content.
- Chart content changes require a chart version bump in the app repository.
- App repositories publish their chart to `oci://ghcr.io/OWNER/charts/CHART`.
- Sugarkube pins the chart version with the app's version file and uses that pin
  for cluster deployment orchestration.


## Chart pin status and explicit bump workflow

Image tags and chart versions are separate deployment coordinates. `just app-deploy tag=...` changes only the image tag passed to Helm; it does **not** discover, select, or bump a newer chart. Default deploys stay pinned and reproducible through `docs/apps/<app>.version`.

Before release operations, inspect the committed chart pin:

```bash
just app-chart-status app=dspace
```

The status command prints the app name, chart ref, pinned version, chart `appVersion`, best-effort digest, and pin file. When registry metadata is available and the pin is older than the newest published semver chart, it warns loudly and prints the exact `just app-chart-bump` command to run. If registry/latest detection is unavailable because of network, auth, or missing tooling, deploys still use the committed pin and the status command prints a manual inspection hint.

When an app repository publishes a new chart that Sugarkube should consume, bump the pin explicitly:

```bash
just app-chart-bump app=dspace version=0.1.3
git add docs/apps/dspace.version
git commit -m "Bump dspace chart pin to 0.1.3"
git push
```

`app-chart-bump` validates the requested chart with `helm show chart <chart-ref> --version <version>`, edits only `docs/apps/<app>.version`, and prints the resulting diff. Do not use `chart=latest` or silent auto-upgrade behavior for production; commit chart pin bumps before or with release operations.

## App config file shape

Generic recipes load a simple shell/dotenv-style config with
[`scripts/app_config.py`](../scripts/app_config.py), using only Python stdlib so
they do not require `yq`. Example files live under
[`docs/examples/apps/`](examples/apps/) and may be copied into a local config
directory such as `apps/APP.env`. Operators may also set
`SUGARKUBE_APP_CONFIG_DIR` to point at another directory.

Config lookup order is:

1. an explicit `config=<path>` passed to a generic recipe;
2. `${SUGARKUBE_APP_CONFIG_DIR}/${app}.env` when `SUGARKUBE_APP_CONFIG_DIR` is set;
3. `apps/${app}.env` in the local clone; and
4. `docs/examples/apps/${app}.env` for the current example apps.

Rules for app config files:

- Use one `KEY=value` assignment per line.
- Quote values only when the shell requires it.
- Keep values chains comma-separated and ordered from base to overlay.
- Keep verify paths comma-separated with leading slashes.
- Do not store secrets in app config files.

Required keys for the generic recipes:

| Key | Purpose |
| --- | --- |
| `SUGARKUBE_APP` | Local Sugarkube app slug used by generic commands. |
| `SUGARKUBE_RELEASE` | Helm release name. |
| `SUGARKUBE_NAMESPACE` | Kubernetes namespace. |
| `SUGARKUBE_CHART` | Helm OCI chart reference. |
| `SUGARKUBE_VERSION_FILE` | Chart version pin file. |
| `SUGARKUBE_PROD_TAG_FILE` | Production-approved tag pin file. |
| `SUGARKUBE_VALUES_DEV` | Values chain for `env=dev`. |
| `SUGARKUBE_VALUES_STAGING` | Values chain for `env=staging`. |
| `SUGARKUBE_VALUES_PROD` | Values chain for `env=prod`. |
| `SUGARKUBE_STATUS_HOST_KEY` | Dotted Helm values key used to discover the public host. |
| `SUGARKUBE_VERIFY_PATHS` | Comma-separated HTTP paths that `just app-verify` executes after deploy. |
| `SUGARKUBE_DEBUG_SELECTOR` | Kubernetes label selector for app pod logs/debugging. |

Example local setup:

```bash
mkdir -p apps
cp docs/examples/apps/dspace.env apps/dspace.env
export SUGARKUBE_APP_CONFIG_DIR=apps
```

## Generic command surface

These recipes are implemented in the root `justfile` and use the app config
lookup order above.

```bash
# Deploy or install a specific immutable candidate into an environment.
just app-deploy app=dspace env=staging tag=main-REPLACE_SHORTSHA

# Redeploy an existing release with a specific immutable tag.
just app-redeploy app=dspace env=staging tag=main-REPLACE_SHORTSHA

# Promote an approved immutable tag to production.
just app-promote-prod app=dspace tag=main-REPLACE_SHORTSHA

# Inspect and intentionally bump the chart pin.
just app-chart-status app=dspace
just app-chart-bump app=dspace version=0.1.3

# Inspect Kubernetes and Helm status for an app environment.
just app-status app=dspace env=staging

# Execute HTTP verification paths for an app environment. Fails non-zero if any path fails.
just app-verify app=dspace env=staging

# Print generated curl commands without executing them.
just app-verify app=dspace env=staging print_only=1

# Print the resolved app config for review/debugging.
just app-config app=dspace env=staging
```

Migration/TODO note: the mature `dspace-oci-deploy`/`dspace-oci-redeploy`,
`tokenplace-oci-deploy`/`tokenplace-oci-redeploy`, and
`danielsmith-oci-deploy`/`danielsmith-oci-redeploy` compatibility paths
intentionally remain in place for now. Generic `app-deploy` and `app-redeploy`
support all three apps, so prefer the generic recipes for new runbooks and app
onboarding, but thinning the remaining deploy/redeploy wrappers is deferred to a
follow-up PR. Production promotion wrappers such as
`just tokenplace-oci-promote-prod tag=main-REPLACE_SHORTSHA` remain documented as
thin generic shims over the shared production promotion flow.

## Current example configs

The example configs in `docs/examples/apps/` intentionally are not platform
defaults. They are scaffolds for future local configs and tests. Shared verify
paths must stay valid for every environment that consumes an app config.
`app-verify` cannot currently express environment-specific runtime JSON files
or optional paths safely, so environment-specific runtime files such as
danielsmith.io `/runtime/github-metrics.json` belong in documented manual
staging/prod curl/jq/log verification steps after `app-verify`, not in the
shared `SUGARKUBE_VERIFY_PATHS` value:

- [`docs/examples/apps/dspace.env`](examples/apps/dspace.env)
- [`docs/examples/apps/tokenplace.env`](examples/apps/tokenplace.env)
- [`docs/examples/apps/danielsmith.env`](examples/apps/danielsmith.env)
- [`docs/examples/apps/jobbot3000.env`](examples/apps/jobbot3000.env)

Current values chains:

| App | dev | staging | prod | Verify paths |
| --- | --- | --- | --- | --- |
| dspace | `docs/examples/dspace.values.dev.yaml` | `docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml` | `docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.prod.yaml` | `/config.json,/healthz,/livez` |
| token.place | `docs/examples/tokenplace.values.dev.yaml` | `docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.staging.yaml` | `docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.prod.yaml` | `/,/livez,/healthz,/relay/diagnostics` |
| danielsmith.io | `docs/examples/danielsmith.values.dev.yaml` | `docs/examples/danielsmith.values.dev.yaml,docs/examples/danielsmith.values.staging.yaml` | `docs/examples/danielsmith.values.dev.yaml,docs/examples/danielsmith.values.prod.yaml` | `/,/livez,/healthz` |
| jobbot3000 | `docs/examples/jobbot3000.values.dev.yaml` | `docs/examples/jobbot3000.values.dev.yaml,docs/examples/jobbot3000.values.staging.yaml` | `docs/examples/jobbot3000.values.dev.yaml,docs/examples/jobbot3000.values.prod.yaml` | `/,/healthz,/livez` |
