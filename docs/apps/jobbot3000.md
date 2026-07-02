# jobbot3000 on Sugarkube

This is the canonical Sugarkube runbook for deploying jobbot3000 from app-owned GHCR artifacts. jobbot3000 is a static, offline-capable, browser-only job application tracker. Sugarkube serves the web app; private tracker data stays in each user's browser IndexedDB and is never stored in Kubernetes.

## Artifact model

- App repository responsibilities: build `ghcr.io/futuroptimist/jobbot3000`, publish immutable image tags, maintain the Helm chart, and publish immutable chart versions to `oci://ghcr.io/futuroptimist/charts/jobbot3000`.
- Sugarkube responsibilities: select `dev`, `staging`, or `prod`; load `docs/examples/apps/jobbot3000.env` or a local override; pin chart and production tags; install or upgrade Helm; verify rollout status and public paths.
- Cloudflare responsibilities: DNS and Tunnel routes to Traefik are outside Helm and must exist before public verification.

| Coordinate | Value |
| --- | --- |
| Image | `ghcr.io/futuroptimist/jobbot3000` |
| Chart | `oci://ghcr.io/futuroptimist/charts/jobbot3000` |
| Release | `jobbot3000` |
| Namespace | `jobbot3000` |
| App config | `docs/examples/apps/jobbot3000.env` |
| Chart version pin | `docs/apps/jobbot3000.version` |
| Production tag pin | `docs/apps/jobbot3000.prod.tag` |
| Verify paths | `/`, `/healthz`, `/livez` |
| Container port | `8080` |

### Artifact links

Use these links before changing a deployment so the workflow runs, package versions, and source paths all agree.

| Artifact | Link |
| --- | --- |
| App repository | [jobbot3000 app repository](https://github.com/futuroptimist/jobbot3000) |
| Image workflow | [Recent image workflow runs](https://github.com/futuroptimist/jobbot3000/actions/workflows/ci-image.yml) |
| Successful main image runs | [Successful main image workflow runs](https://github.com/futuroptimist/jobbot3000/actions/workflows/ci-image.yml?query=branch%3Amain+is%3Asuccess) |
| GHCR image package | [GHCR image package versions](https://github.com/futuroptimist/jobbot3000/pkgs/container/jobbot3000) |
| Chart workflow | [Recent chart workflow runs](https://github.com/futuroptimist/jobbot3000/actions/workflows/ci-helm.yml) |
| GHCR chart package | [GHCR chart package versions](https://github.com/futuroptimist/jobbot3000/pkgs/container/charts%2Fjobbot3000) |
| Dockerfile | [Application Dockerfile](https://github.com/futuroptimist/jobbot3000/blob/main/Dockerfile) |
| Chart source path | [Helm chart source](https://github.com/futuroptimist/jobbot3000/tree/main/charts/jobbot3000) |
| Image release docs | [jobbot3000 GHCR image release docs](https://github.com/futuroptimist/jobbot3000/blob/main/docs/release-ghcr.md) |
| Helm release docs | [jobbot3000 Helm release docs](https://github.com/futuroptimist/jobbot3000/blob/main/docs/release-helm.md) |
| App release guide | [jobbot3000 release docs index](https://github.com/futuroptimist/jobbot3000/tree/main/docs) |

## Data, backup, and seeding model

jobbot3000's production deployment model is a static browser-local tracker. Kubernetes serves only the static web container. The application data model is IndexedDB-first: applications, outreach, interviews, offers, outcomes, notes, contacts, resume links, Drive links, private settings, and imported backups live in the user's browser storage.

Backups and restores are user-driven through the browser UI:

- CSV is the spreadsheet-compatible, human-editable backup format.
- JSON and NDJSON are the full-fidelity backup and restore formats.
- Dev, staging, and production seed data must be imported manually through the browser UI.

Do not bake real user data into Docker images, Helm charts, Helm values, Kubernetes Secrets, ConfigMaps, PVCs, Sugarkube docs, or Sugarkube examples. The example values intentionally do not configure server-side persistence.

## Environment topology

- `env=dev`: base values in `docs/examples/jobbot3000.values.dev.yaml`; ingress disabled by default and image tag shown as the immutable placeholder `main-REPLACE_SHORTSHA`.
- `env=staging`: values chain `docs/examples/jobbot3000.values.dev.yaml,docs/examples/jobbot3000.values.staging.yaml`; placeholder host `staging.jobbot3000.example.test`.
- `env=prod`: values chain `docs/examples/jobbot3000.values.dev.yaml,docs/examples/jobbot3000.values.prod.yaml`; placeholder host `jobbot3000.example.test`.

Replace placeholder hosts in a local operator config or overlay before using a real cluster. Keep Cloudflare DNS and Tunnel routing outside Helm.

## Find or publish GHCR image

Find the successful image workflow in the jobbot3000 app repo and copy the immutable branch-SHA or release tag. Do not deploy `latest`, `main-latest`, a bare branch name, or an environment name.

Web UI shortcuts:

- Open [recent image workflow runs](https://github.com/futuroptimist/jobbot3000/actions/workflows/ci-image.yml) or [successful main image runs](https://github.com/futuroptimist/jobbot3000/actions/workflows/ci-image.yml?query=branch%3Amain+is%3Asuccess).
- Open [GHCR image package versions](https://github.com/futuroptimist/jobbot3000/pkgs/container/jobbot3000).
- Copy the immutable tag from a successful workflow summary or package version.

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

## Confirm/publish OCI chart

Sugarkube deploys the chart version pinned in `docs/apps/jobbot3000.version`. Use [recent chart workflow runs](https://github.com/futuroptimist/jobbot3000/actions/workflows/ci-helm.yml), [GHCR chart package versions](https://github.com/futuroptimist/jobbot3000/pkgs/container/charts%2Fjobbot3000), and [the chart source](https://github.com/futuroptimist/jobbot3000/tree/main/charts/jobbot3000) to confirm the pinned immutable version.

```bash
just app-chart-status app=jobbot3000
```

```bash
CHART_VERSION=$(sed -e 's/#.*$//' -e '/^[[:space:]]*$/d' docs/apps/jobbot3000.version | head -n 1)
helm show chart oci://ghcr.io/futuroptimist/charts/jobbot3000 --version "$CHART_VERSION"
```

If registry validation was unavailable when this runbook was last edited, operators should run one of the commands above before the first deploy. If the app repo publishes a new chart, bump the Sugarkube pin explicitly:

```bash
just app-chart-bump app=jobbot3000 version=0.1.1
```

## Deploy and verify staging

```bash
just app-deploy app=jobbot3000 env=staging tag=main-REPLACE_SHORTSHA
```

```bash
just app-status app=jobbot3000 env=staging
```

```bash
just app-verify app=jobbot3000 env=staging
```

Print the generated checks without executing them:

```bash
just app-verify app=jobbot3000 env=staging print_only=1
```

## Redeploy, promote, and rollback

Redeploy staging or production with a specific immutable tag:

```bash
just app-redeploy app=jobbot3000 env=staging tag=main-REPLACE_SHORTSHA
```

Promote production only after staging sign-off, using the exact immutable image tag that passed staging:

```bash
just app-promote-prod app=jobbot3000 tag=main-REPLACE_SHORTSHA
```

Rollback by redeploying the previous known-good immutable image tag:

```bash
just app-redeploy app=jobbot3000 env=prod tag=main-REPLACE_PREVIOUS_SHORTSHA
```

After any production deploy or rollback, run:

```bash
just app-status app=jobbot3000 env=prod
```

```bash
just app-verify app=jobbot3000 env=prod
```
