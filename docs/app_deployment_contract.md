# Sugarkube app deployment contract

Sugarkube is moving toward a generic app deployment surface where each app is
identified by a small local config file and deployed with shared `just` recipes.
This page is the contract future implementation work will target; it does not
change current `justfile` deployment behavior.

The existing app-specific recipes for dspace, token.place, and danielsmith.io
remain compatibility wrappers until the generic recipes are implemented.

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

Future onboarding examples include wove and jobbot3000, but they should only get
Sugarkube app configs after their app repositories have published compatible
images and charts.

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

The current apps map to that model as examples:

| App | Image | Chart | Release | Namespace | Version pin | Prod tag pin |
| --- | --- | --- | --- | --- | --- | --- |
| dspace | `ghcr.io/democratizedspace/dspace` | `oci://ghcr.io/democratizedspace/charts/dspace` | `dspace` | `dspace` | `docs/apps/dspace.version` | `docs/apps/dspace.prod.tag` |
| token.place | `ghcr.io/futuroptimist/tokenplace-relay` | `oci://ghcr.io/futuroptimist/charts/tokenplace` | `tokenplace` | `tokenplace` | `docs/apps/tokenplace.version` | `docs/apps/tokenplace.prod.tag` |
| danielsmith.io | `ghcr.io/futuroptimist/danielsmith.io` | `oci://ghcr.io/futuroptimist/charts/danielsmith` | `danielsmith` | `danielsmith` | `docs/apps/danielsmith.version` | `docs/apps/danielsmith.prod.tag` |

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

## App config file shape

Future generic recipes will load a simple shell/dotenv-style config so they do
not require `yq`. Example files live under [`docs/examples/apps/`](examples/apps/)
and may be copied into a local config directory such as `apps/APP.env`. Operators
may also set `SUGARKUBE_APP_CONFIG_DIR` to point at another directory.

Rules for app config files:

- Use one `KEY=value` assignment per line.
- Quote values only when the shell requires it.
- Keep values chains comma-separated and ordered from base to overlay.
- Keep verify paths comma-separated with leading slashes.
- Do not store secrets in app config files.

Required keys for the planned generic recipes:

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
| `SUGARKUBE_VERIFY_PATHS` | Comma-separated HTTP paths for post-deploy verification. |
| `SUGARKUBE_DEBUG_SELECTOR` | Kubernetes label selector for app pod logs/debugging. |

Example local setup:

```bash
mkdir -p apps
cp docs/examples/apps/dspace.env apps/dspace.env
export SUGARKUBE_APP_CONFIG_DIR=apps
```

## Planned generic command surface

P5 will implement these command shapes. They are documented here so app repos can
align their artifacts before Sugarkube changes behavior.

```bash
# Deploy or install a specific immutable candidate into an environment.
just app-deploy app=dspace env=staging tag=main-REPLACE_SHORTSHA

# Redeploy an existing release with a specific immutable tag.
just app-redeploy app=dspace env=staging tag=main-REPLACE_SHORTSHA

# Promote an approved immutable tag to production.
just app-promote-prod app=dspace tag=v1.2.3

# Inspect Kubernetes and Helm status for an app environment.
just app-status app=dspace env=staging

# Run HTTP verification paths for an app environment.
just app-verify app=dspace env=staging

# Print the resolved app config for review/debugging.
just app-config app=dspace env=staging
```

The compatibility wrappers will remain during migration. For example,
`just dspace-oci-deploy env=staging tag=main-REPLACE_SHORTSHA` and
`just tokenplace-oci-promote-prod tag=main-REPLACE_SHORTSHA` continue to be the
current operational commands until generic recipes replace their internals.

## Current example configs

The example configs in `docs/examples/apps/` intentionally are not platform
defaults. They are scaffolds for future local configs and tests:

- [`docs/examples/apps/dspace.env`](examples/apps/dspace.env)
- [`docs/examples/apps/tokenplace.env`](examples/apps/tokenplace.env)
- [`docs/examples/apps/danielsmith.env`](examples/apps/danielsmith.env)

Current values chains:

| App | dev | staging | prod | Verify paths |
| --- | --- | --- | --- | --- |
| dspace | `docs/examples/dspace.values.dev.yaml` | `docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml` | `docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.prod.yaml` | `/config.json,/healthz,/livez` |
| token.place | `docs/examples/tokenplace.values.dev.yaml` | `docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.staging.yaml` | `docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.prod.yaml` | `/,/livez,/healthz,/relay/diagnostics` |
| danielsmith.io | `docs/examples/danielsmith.values.dev.yaml` | `docs/examples/danielsmith.values.dev.yaml,docs/examples/danielsmith.values.staging.yaml` | `docs/examples/danielsmith.values.dev.yaml,docs/examples/danielsmith.values.prod.yaml` | `/,/livez,/healthz` |
