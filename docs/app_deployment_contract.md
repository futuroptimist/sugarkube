# Sugarkube app deployment contract

This contract defines the cross-app shape that future Sugarkube app automation will use. It is a
specification and docs scaffold only: the existing `justfile` app-specific helpers remain the live
entry points until the generic recipes are implemented.

Sugarkube's app boundary is intentionally small:

- **App repositories** own the application source, Dockerfile, Helm chart, and GHCR publishing.
- **Sugarkube** owns cluster and environment deployment orchestration from local app config files.

The current examples are dspace, token.place, and danielsmith.io. Future apps such as wove and
jobbot3000 should use this same contract once their app repositories have charts and publishing
workflows.

## Standard artifact model

Every app must identify these deployment artifacts and runtime checks:

| Field | Required shape | Purpose |
| --- | --- | --- |
| Image | `ghcr.io/OWNER/IMAGE` | Container image repository published by the app repo. |
| Chart | `oci://ghcr.io/OWNER/charts/CHART` | Immutable Helm OCI chart published by the app repo. |
| Release name | Stable Helm release name, usually the app slug. | Selects the Helm release to install, upgrade, and inspect. |
| Namespace | Stable Kubernetes namespace, usually the app slug. | Isolates app resources and status checks. |
| Chart version pin file | Repo-local text file such as `docs/apps/APP.version`. | Records the chart version Sugarkube should deploy. |
| Prod-approved tag pin file | Optional repo-local text file such as `docs/apps/APP.prod.tag`. | Records the image tag approved for production promotion. |
| Values chain per environment | Comma-separated values files for `dev`, `staging`, and `prod`. | Keeps base settings separate from environment routing and sizing. |
| Validation URLs and paths | Host resolved from Helm values plus a comma-separated path list. | Powers post-deploy smoke checks and runbook commands. |

The values chain is ordered from shared base to environment-specific overlay. For example, staging
usually looks like `docs/examples/APP.values.dev.yaml,docs/examples/APP.values.staging.yaml`, while
production uses `docs/examples/APP.values.dev.yaml,docs/examples/APP.values.prod.yaml`.

## Standard image tag model

Deployment tags must identify what is running without depending on mutable names.

Allowed deployment tags:

- **Immutable branch-SHA tag:** `main-REPLACE_SHORTSHA`, where `REPLACE_SHORTSHA` is a real short
  Git SHA from the app repository. This is the default shape for staging validation and most
  non-prod deploys.
- **Mutable branch convenience tag:** `main-latest`. This is allowed only for explicitly documented
  non-prod bootstrap or rapid iteration. It is not acceptable for production promotion.
- **Release or stable tag:** `v1.2.3`, `3.1.0`, or another app-specific stable tag documented by
  the app repo.

Disallowed deployment tags:

- `latest`
- bare branch names such as `main`, `master`, or `develop`
- environment names such as `dev`, `staging`, `prod`, or `production`

Environment selection belongs in Sugarkube values overlays and kubeconfig selection. Image tags
belong to the app release lineage. Do not encode an environment as the deployment tag.

## Standard chart publishing model

- Chart versions are immutable once published to GHCR.
- App repos must bump the chart version whenever chart content changes.
- App repos own their Dockerfile, app chart, and GHCR image/chart publishing workflows.
- Sugarkube owns deployment orchestration: choosing the environment, resolving the app config,
  reading chart and prod tag pins, applying values chains, and running status/verification checks.

A Sugarkube PR should update the chart version pin file only after the app repo has published that
chart version.

## App config file shape

Future generic recipes will read a simple shell/dotenv-style config so they do not require `yq`.
Each file must be safe to source in Bash: use `KEY=value` pairs, quote values only when needed, and
keep comments on their own lines.

Example configs live under `docs/examples/apps/` and are templates, not active platform defaults.
Copy one into a local config directory before using the future generic recipes:

```bash
mkdir -p apps
cp docs/examples/apps/tokenplace.env apps/tokenplace.env
```

Operators may also keep app configs outside the repository and point Sugarkube at them:

```bash
export SUGARKUBE_APP_CONFIG_DIR=/srv/sugarkube-apps
just app-config app=tokenplace env=staging
```

Required keys for the P5 generic recipes:

| Key | Description |
| --- | --- |
| `SUGARKUBE_APP` | Stable app slug used to find the config. |
| `SUGARKUBE_RELEASE` | Helm release name. |
| `SUGARKUBE_NAMESPACE` | Kubernetes namespace. |
| `SUGARKUBE_CHART` | Helm OCI chart reference. |
| `SUGARKUBE_VERSION_FILE` | File containing the pinned chart version. |
| `SUGARKUBE_PROD_TAG_FILE` | File containing the prod-approved image tag, or an empty value when unused. |
| `SUGARKUBE_VALUES_DEV` | Values chain for `env=dev`. |
| `SUGARKUBE_VALUES_STAGING` | Values chain for `env=staging`. |
| `SUGARKUBE_VALUES_PROD` | Values chain for `env=prod`. |
| `SUGARKUBE_STATUS_HOST_KEY` | Dotted Helm values key used to find the public host, for example `ingress.host`. |
| `SUGARKUBE_VERIFY_PATHS` | Comma-separated HTTP paths for smoke verification. |
| `SUGARKUBE_DEBUG_SELECTOR` | Kubernetes label selector for app pod logs and debug output. |

## Future generic command surface

P5 will implement the commands below. They are documented here so app repos and Sugarkube docs can
align before behavior changes land.

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

Expected behavior once implemented:

1. `app-config` resolves and prints the config file, selected values chain, chart version pin, prod
   tag pin, status host key, verify paths, and debug selector.
2. `app-deploy` installs or upgrades the app with the selected values chain and immutable image tag.
3. `app-redeploy` performs an upgrade-only refresh for an existing release and waits for rollout.
4. `app-promote-prod` deploys `env=prod`, using the explicit tag or the prod-approved tag pin file.
5. `app-status` prints pods, ingress, Helm release status, and the resolved public URL when present.
6. `app-verify` runs the app's configured HTTP path checks against the environment host.

Until P5 lands, keep using the existing app-specific wrappers documented in each app runbook.

## Current app examples

| App | Image | Chart | Release / namespace | Version pin | Prod tag pin | Verify paths |
| --- | --- | --- | --- | --- | --- | --- |
| dspace | `ghcr.io/democratizedspace/dspace` | `oci://ghcr.io/democratizedspace/charts/dspace` | `dspace` / `dspace` | `docs/apps/dspace.version` | `docs/apps/dspace.prod.tag` | `/config.json,/healthz,/livez` |
| token.place | `ghcr.io/futuroptimist/tokenplace-relay` | `oci://ghcr.io/futuroptimist/charts/tokenplace` | `tokenplace` / `tokenplace` | `docs/apps/tokenplace.version` | `docs/apps/tokenplace.prod.tag` | `/,/livez,/healthz,/relay/diagnostics` |
| danielsmith.io | `ghcr.io/futuroptimist/danielsmith.io` | `oci://ghcr.io/futuroptimist/charts/danielsmith` | `danielsmith` / `danielsmith` | `docs/apps/danielsmith.version` | `docs/apps/danielsmith.prod.tag` | `/,/livez,/healthz` |

See the template configs for the complete values chains:

- [`docs/examples/apps/dspace.env`](examples/apps/dspace.env)
- [`docs/examples/apps/tokenplace.env`](examples/apps/tokenplace.env)
- [`docs/examples/apps/danielsmith.env`](examples/apps/danielsmith.env)
