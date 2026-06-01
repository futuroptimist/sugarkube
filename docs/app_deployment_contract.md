# Sugarkube app deployment contract

This contract defines the target deployment shape for apps that run on a Sugarkube-managed
Kubernetes environment. It is a **specification and docs scaffold only**: the current app-specific
`just` recipes remain in place, and the generic commands below are reserved for the follow-up
implementation.

Sugarkube should be generic deployment sugar for many app repositories. App repositories own their
build and release artifacts; Sugarkube owns cluster and environment orchestration.

## Ownership boundary

App repositories own:

- the application source code;
- the app `Dockerfile` and published image;
- the app Helm chart and chart version bumps;
- GHCR publishing workflows for images and charts; and
- release notes or app-specific validation requirements.

Sugarkube owns:

- local app deployment config discovery;
- environment-specific kubeconfig selection;
- Helm install, upgrade, promote, status, and verify orchestration;
- app runbooks that explain how to operate a release on the cluster; and
- compatibility wrappers for existing app-specific workflows while the generic flow lands.

Future apps such as `wove` and `jobbot3000` should onboard by publishing the same artifact set and
adding a local app config. They should not require hard-coded Sugarkube recipes when the generic flow
is available.

## Standard artifact model

Every Sugarkube app config describes these artifacts and deployment coordinates:

| Field | Standard | Notes |
| --- | --- | --- |
| Image | `ghcr.io/OWNER/IMAGE` | Published by the app repository. |
| Chart | `oci://ghcr.io/OWNER/charts/CHART` | Published by the app repository as an OCI Helm chart. |
| Release name | Stable lowercase app release, for example `tokenplace` | Used for Helm release lookup and rollout selection. |
| Namespace | Stable lowercase namespace, often matching the release | Sugarkube creates or targets this namespace during deploys. |
| Chart version pin file | Repo-relative text file, for example `docs/apps/tokenplace.version` | Contains the immutable chart version Sugarkube should deploy. |
| Production approved tag pin file | Optional repo-relative text file, for example `docs/apps/tokenplace.prod.tag` | Contains the image tag approved for production promotion. |
| Values chain per env | Comma-separated repo-relative values files | Base values first, then the env overlay. |
| Validation URLs and paths | Host value key plus comma-separated paths | Used by status and verify recipes to print and curl app endpoints. |

The checked-in files under [`docs/examples/apps/`](examples/apps/) are examples only. Operators may
copy one into a local config directory such as `apps/tokenplace.env`, or point
`SUGARKUBE_APP_CONFIG_DIR` at another directory, once the generic recipes support config discovery.

## Standard image tag model

Deployment tags must identify exactly what was built:

- **Immutable branch-SHA tag:** use this for normal deploys, staging sign-off, rollback, and most
  production promotions. Example: `main-REPLACE_SHORTSHA`.
- **Mutable branch convenience tag:** allowed only for explicitly documented non-production bootstrap
  or rapid iteration. Example: `main-latest`.
- **Semantic or release tag:** allowed when the app repository cuts a stable release. Examples:
  `v1.2.3`, `3.1.0`, or another project-specific stable tag documented by that app.

Do **not** deploy with ambiguous mutable tags:

- `latest`
- bare branch names such as `main`, `master`, or `develop`
- environment names such as `dev`, `staging`, `prod`, or `production`

Environment routing belongs in values files. Image tags describe released code and must not double as
environment names.

## Standard chart publishing model

- Chart versions are immutable after publication.
- Any chart content change requires a chart version bump before publishing.
- The app repository owns its chart source and GHCR chart publishing workflow.
- Sugarkube records the desired chart version in the app's chart version pin file and deploys that
  exact version.
- Image-only releases can reuse an existing chart version when the chart content did not change.
- Chart changes and image changes may ship together, but both the chart version and image tag must be
  explicit in the deployment review.

## App config file shape

Use simple shell-compatible `KEY=value` files so future `just` recipes can parse them without YAML
helpers. Keep values unquoted unless a value truly needs shell quoting.

```bash
# Example only. Copy to apps/myapp.env or set SUGARKUBE_APP_CONFIG_DIR later.
SUGARKUBE_APP=myapp
SUGARKUBE_IMAGE=ghcr.io/yourorg/myapp
SUGARKUBE_RELEASE=myapp
SUGARKUBE_NAMESPACE=myapp
SUGARKUBE_CHART=oci://ghcr.io/yourorg/charts/myapp
SUGARKUBE_VERSION_FILE=docs/apps/myapp.version
SUGARKUBE_PROD_TAG_FILE=docs/apps/myapp.prod.tag
SUGARKUBE_VALUES_DEV=docs/examples/myapp.values.dev.yaml
SUGARKUBE_VALUES_STAGING=docs/examples/myapp.values.dev.yaml,docs/examples/myapp.values.staging.yaml
SUGARKUBE_VALUES_PROD=docs/examples/myapp.values.dev.yaml,docs/examples/myapp.values.prod.yaml
SUGARKUBE_STATUS_HOST_KEY=ingress.host
SUGARKUBE_VERIFY_PATHS=/,/livez,/healthz
SUGARKUBE_DEBUG_SELECTOR=app.kubernetes.io/name=myapp
```

Rules for config files:

- `SUGARKUBE_APP` is the app identifier passed as `app=`.
- `SUGARKUBE_IMAGE` is documented for humans and release review, even when deploy recipes only pass a
  tag to the chart.
- `SUGARKUBE_VALUES_DEV`, `SUGARKUBE_VALUES_STAGING`, and `SUGARKUBE_VALUES_PROD` are comma-separated
  Helm values chains in apply order.
- `SUGARKUBE_STATUS_HOST_KEY` is the dotted values key that resolves the public host from Helm
  values, commonly `ingress.host`.
- `SUGARKUBE_VERIFY_PATHS` is a comma-separated path list. Each path is checked against the resolved
  host for the selected environment.
- `SUGARKUBE_DEBUG_SELECTOR` selects app pods for log and rollout diagnostics.

## Future generic command surface

The follow-up implementation should expose this command shape while preserving existing app-specific
recipes as compatibility wrappers:

```bash
just app-config app=tokenplace env=staging
```

```bash
just app-deploy app=tokenplace env=staging tag=main-REPLACE_SHORTSHA
```

```bash
just app-redeploy app=tokenplace env=staging tag=main-REPLACE_SHORTSHA
```

```bash
just app-promote-prod app=tokenplace tag=main-REPLACE_SHORTSHA
```

```bash
just app-status app=tokenplace env=staging
```

```bash
just app-verify app=tokenplace env=staging
```

Expected behavior for the future recipes:

- `app-config` prints the resolved config, selected values chain, release, namespace, chart, chart
  version file, optional prod tag file, status host key, verify paths, and debug selector.
- `app-deploy` performs an install-or-upgrade with an explicit immutable tag.
- `app-redeploy` performs an upgrade-only refresh of an already deployed immutable tag.
- `app-promote-prod` deploys `env=prod`, requiring either `tag=` or the app's prod-approved tag pin
  file.
- `app-status` selects the environment kubeconfig, prints pods and ingress, and reports the public
  URL when available.
- `app-verify` selects the environment kubeconfig, checks rollout status, and curls each configured
  validation path.

## Current app examples

The current app configs are intentionally examples, not platform defaults:

- [`docs/examples/apps/dspace.env`](examples/apps/dspace.env)
- [`docs/examples/apps/tokenplace.env`](examples/apps/tokenplace.env)
- [`docs/examples/apps/danielsmith.env`](examples/apps/danielsmith.env)

Current app-specific runbooks remain authoritative until the generic recipes are implemented:

- [`docs/apps/dspace.md`](apps/dspace.md)
- [`docs/apps/tokenplace.md`](apps/tokenplace.md)
- [`docs/apps/danielsmith.md`](apps/danielsmith.md)
