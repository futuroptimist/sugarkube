# Sugarkube app deployment contract

This page defines the target cross-app deployment contract that future generic
Sugarkube recipes will implement. It is a **specification and scaffold only**:
today's app-specific `just` recipes and Helm OCI helpers remain the live
interfaces until the generic recipes are implemented.

Sugarkube's role is cluster and environment orchestration. Each app repository
continues to own its application source, Dockerfile, Helm chart, release process,
and GHCR publishing workflow.

## Standard artifact model

Every Sugarkube app should publish and deploy the same set of artifacts and
metadata:

| Field | Contract |
| --- | --- |
| Image | `ghcr.io/<owner>/<image>` |
| Chart | `oci://ghcr.io/<owner>/charts/<chart>` |
| Release name | Stable Helm release name, normally the app slug. |
| Namespace | Stable Kubernetes namespace, normally the app slug. |
| Chart version pin file | A repo-local file such as `docs/apps/<app>.version` containing the immutable chart version Sugarkube should deploy. |
| Prod-approved tag pin file | Optional repo-local file such as `docs/apps/<app>.prod.tag` containing the immutable image tag approved for production. |
| Values chain per environment | Comma-separated Helm values files, ordered from base to environment overlay. |
| Validation URLs/paths | Environment host plus one or more HTTP paths that prove the app is serving the expected workload. |

The chart and image names are intentionally separate. A chart may deploy an
image whose repository name is not identical to the chart name, but that mapping
belongs in the app-owned chart or environment values, not in ad hoc deploy
commands.

## Standard image tag model

Deployment tags must identify what is actually running. Use these tag classes:

- **Immutable branch-SHA tag:** `main-REPLACE_SHORTSHA` or an equivalent
  branch-plus-short-SHA tag. This is the preferred staging, promotion, rollback,
  and incident-response tag shape.
- **Mutable branch convenience tag:** `main-latest`. This is allowed only for
  explicitly documented non-production bootstrap or fast iteration. Never use it
  for production sign-off or promotion.
- **Release or stable tag:** `v1.2.3`, `3.1.0`, or a project-specific stable tag
  documented by the app repository.

Do **not** use these as deployment tags:

- `latest`
- bare branch names such as `main`, `master`, `develop`, or `release`
- environment names such as `dev`, `staging`, `prod`, or `production`

Environment names select kubeconfig context and values overlays. Image tags
select the released application build. Keep those concerns separate.

## Standard chart publishing model

- Chart versions are immutable after publishing to GHCR.
- App repositories must bump the chart version whenever chart content changes,
  including templates, default values, probes, labels, or chart metadata.
- App repositories own their Dockerfile, image publishing, Helm chart, chart
  versioning, and GHCR workflow.
- Sugarkube owns cluster/environment deployment orchestration, local chart
  version pins, production tag approvals, and runbooks.
- Sugarkube deploys the chart version in the app's version pin file unless an
  emergency runbook explicitly says otherwise.

## App config shape

Future generic recipes will load one shell/dotenv-style app config file per app.
The examples in [`docs/examples/apps/`](examples/apps/) are documentation
scaffolds only. Copy one into a local config directory such as `apps/<app>.env`,
or set `SUGARKUBE_APP_CONFIG_DIR` to a directory that contains `<app>.env` files.

The file format intentionally avoids YAML-only tooling so a POSIX shell or Bash
recipe can parse it without `yq`:

```dotenv
SUGARKUBE_APP=example
SUGARKUBE_RELEASE=example
SUGARKUBE_NAMESPACE=example
SUGARKUBE_CHART=oci://ghcr.io/example/charts/example
SUGARKUBE_VERSION_FILE=docs/apps/example.version
SUGARKUBE_PROD_TAG_FILE=docs/apps/example.prod.tag
SUGARKUBE_VALUES_DEV=docs/examples/example.values.dev.yaml
SUGARKUBE_VALUES_STAGING=docs/examples/example.values.dev.yaml,docs/examples/example.values.staging.yaml
SUGARKUBE_VALUES_PROD=docs/examples/example.values.dev.yaml,docs/examples/example.values.prod.yaml
SUGARKUBE_STATUS_HOST_KEY=ingress.host
SUGARKUBE_VERIFY_PATHS=/,/livez,/healthz
SUGARKUBE_DEBUG_SELECTOR=app.kubernetes.io/name=example
```

Required keys for the first generic implementation:

- `SUGARKUBE_APP`: config/app slug passed to `app=<app>`.
- `SUGARKUBE_RELEASE`: Helm release name.
- `SUGARKUBE_NAMESPACE`: Kubernetes namespace.
- `SUGARKUBE_CHART`: OCI chart reference.
- `SUGARKUBE_VERSION_FILE`: chart version pin file.
- `SUGARKUBE_PROD_TAG_FILE`: production-approved image tag pin file, if the app
  supports production promotion.
- `SUGARKUBE_VALUES_DEV`: dev values chain.
- `SUGARKUBE_VALUES_STAGING`: staging values chain.
- `SUGARKUBE_VALUES_PROD`: production values chain.
- `SUGARKUBE_STATUS_HOST_KEY`: Helm values key that stores the public host.
- `SUGARKUBE_VERIFY_PATHS`: comma-separated HTTP paths for verification.
- `SUGARKUBE_DEBUG_SELECTOR`: Kubernetes label selector for app logs and pod
  inspection.

Keep values chains relative to the Sugarkube repo root unless a runbook clearly
states otherwise.

## Future generic command surface

P5 in the prompt sequence will implement these recipes. They are documented here
now so app repositories and runbooks can align before Sugarkube behavior changes:

```bash
APP=dspace
TAG=main-REPLACE_SHORTSHA
just app-config app="$APP" env=staging
just app-deploy app="$APP" env=staging tag="$TAG"
just app-status app="$APP" env=staging
just app-verify app="$APP" env=staging
```

```bash
APP=dspace
TAG=main-REPLACE_SHORTSHA
just app-redeploy app="$APP" env=staging tag="$TAG"
```

```bash
APP=dspace
TAG=main-REPLACE_SHORTSHA
just app-promote-prod app="$APP" tag="$TAG"
```

Intended semantics:

- `just app-config app=<app> env=<dev|staging|prod>` prints the resolved config,
  values chain, chart version, release, namespace, and verification paths.
- `just app-deploy app=<app> env=<dev|staging|prod> tag=<immutable-tag>` performs
  install-or-upgrade for the pinned chart version and explicit immutable image
  tag.
- `just app-redeploy app=<app> env=<dev|staging|prod> tag=<immutable-tag>` performs
  an upgrade/restart path for an already deployed immutable tag.
- `just app-promote-prod app=<app> tag=<immutable-tag>` deploys the approved tag
  to production and may read the prod tag pin file when `tag=` is omitted.
- `just app-status app=<app> env=<dev|staging|prod>` selects the environment and
  prints Kubernetes/Helm status plus the public URL when available.
- `just app-verify app=<app> env=<dev|staging|prod>` curls the configured
  verification paths for the environment host.

Until those recipes exist, use the existing app-specific wrappers documented in
the app runbooks.

## Current app examples

The current first-class app configs are examples, not platform defaults:

- [`docs/examples/apps/dspace.env`](examples/apps/dspace.env)
- [`docs/examples/apps/tokenplace.env`](examples/apps/tokenplace.env)
- [`docs/examples/apps/danielsmith.env`](examples/apps/danielsmith.env)

These examples model today's known release names, namespaces, chart references,
version pin files, prod tag pin files, values chains, status host keys,
verification paths, and debug selectors.

Future apps such as **wove** and **jobbot3000** should be onboarded by adding
app-owned image/chart publishing first, then copying this config shape into a
local app config. Do not add Sugarkube app configs for future apps until they
have concrete chart and publishing contracts.

## Non-goals for this spec PR

- No `justfile` deployment behavior changes.
- No removal of app-specific recipes.
- No live values changes.
- No secrets, kubeconfig assumptions, or cluster credentials.
