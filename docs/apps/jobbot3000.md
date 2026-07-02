# jobbot3000 on Sugarkube

This is the Sugarkube runbook for deploying jobbot3000 from app-owned GHCR artifacts with the generic `just app-*` recipes. jobbot3000 is a static, browser-only job application tracker: Kubernetes serves the web app, while private tracker data lives in each user's browser IndexedDB.

## Artifact model

- App repository responsibilities: build `ghcr.io/futuroptimist/jobbot3000`, publish immutable image tags, maintain the Helm chart, publish immutable chart versions to `oci://ghcr.io/futuroptimist/charts/jobbot3000`, and document app release details.
- Sugarkube responsibilities: select `dev`, `staging`, or `prod`; load `docs/examples/apps/jobbot3000.env` or a local override; pin chart versions and production image tags; apply values overlays; and run deploy, status, verification, promotion, and rollback commands.
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

## Artifact links

Use these links before changing a deployment so workflow runs, package versions, and source paths all agree.

| Artifact | Link |
| --- | --- |
| App repository | [jobbot3000 app repository](https://github.com/futuroptimist/jobbot3000) |
| Image workflow | [Recent image workflow runs](https://github.com/futuroptimist/jobbot3000/actions/workflows/ci-image.yml) |
| Successful main image runs | [Successful main image workflow runs](https://github.com/futuroptimist/jobbot3000/actions/workflows/ci-image.yml?query=branch%3Amain+is%3Asuccess) |
| GHCR image package | [GHCR image package versions](https://github.com/futuroptimist/jobbot3000/pkgs/container/jobbot3000) |
| Chart workflow | [Recent chart workflow runs](https://github.com/futuroptimist/jobbot3000/actions/workflows/ci-helm.yml) |
| GHCR chart package | [GHCR chart package versions](https://github.com/futuroptimist/jobbot3000/pkgs/container/charts%2Fjobbot3000) |
| Dockerfile | [Application Dockerfile](https://github.com/futuroptimist/jobbot3000/blob/main/Dockerfile) |
| Chart source | [Helm chart source](https://github.com/futuroptimist/jobbot3000/tree/main/charts/jobbot3000) |
| Image release docs | [jobbot3000 image release docs](https://github.com/futuroptimist/jobbot3000/blob/main/docs/ops/image-release.md) |
| Helm release docs | [jobbot3000 Helm release docs](https://github.com/futuroptimist/jobbot3000/blob/main/docs/ops/helm-release.md) |

## Data, backup, and seeding model

jobbot3000 stores private user data in browser IndexedDB. The cluster should only serve the static app and health endpoints; it must not own job applications, outreach messages, interviews, offers, notes, contacts, resume links, Drive links, imported CSV rows, JSON/NDJSON backups, or private user settings.

- CSV is the spreadsheet-compatible, human-editable backup format.
- JSON and NDJSON are full-fidelity backup/restore formats.
- Seed dev, staging, and prod only by manually importing CSV, JSON, or NDJSON through the browser UI.
- Do not bake real user data into images, charts, Helm values, Kubernetes Secrets, ConfigMaps, PVCs, repo fixtures, or Sugarkube docs/examples.
- Do not add server-side persistence for this app; no PVC is expected for jobbot3000.

## Find or publish a GHCR image

Find the successful image workflow in the jobbot3000 app repo and copy the immutable branch-SHA or release tag. Do not deploy `latest`, `main-latest`, a bare branch name, or an environment name.

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
gh run list --repo futuroptimist/jobbot3000 --workflow ci-image.yml --branch main --status success --limit 5
```

If no suitable image exists, publish it from the app repo workflow, then return here with the immutable tag it produced.

```bash
gh workflow run ci-image.yml --repo futuroptimist/jobbot3000 --ref main
```

## Confirm or bump the OCI chart

Sugarkube deploys the chart version pinned in `docs/apps/jobbot3000.version`. The initial pin is sourced from the app repo chart; before the first deploy, validate that GHCR has published the same immutable version.

```bash
just app-chart-status app=jobbot3000
```

```bash
CHART_VERSION=$(sed -e 's/#.*$//' -e '/^[[:space:]]*$/d' docs/apps/jobbot3000.version | head -n 1)
helm show chart oci://ghcr.io/futuroptimist/charts/jobbot3000 --version "$CHART_VERSION"
```

If the chart changed, bump the chart version in the jobbot3000 app repo and publish it there with the chart workflow; do not republish a different chart under an existing OCI version. After the app repo publishes the new chart, update Sugarkube's chart pin:

```bash
just app-chart-bump app=jobbot3000 version=<version>
```

## Deploy and verify staging

Deploy staging with an immutable image tag that came from the jobbot3000 image workflow.

```bash
just app-deploy app=jobbot3000 env=staging tag=main-REPLACE_SHORTSHA
```

Redeploy the same or another approved immutable tag when you need to reapply values or retry a rollout:

```bash
just app-redeploy app=jobbot3000 env=staging tag=main-REPLACE_SHORTSHA
```

Check status and public paths:

```bash
just app-status app=jobbot3000 env=staging
```

```bash
just app-verify app=jobbot3000 env=staging
```

Print the generated curl commands without executing them when debugging host routing:

```bash
just app-verify app=jobbot3000 env=staging print_only=1
```

## Promote production

Promote only after staging sign-off, using the exact immutable image tag that passed staging. Keep `docs/apps/jobbot3000.prod.tag` empty until an operator explicitly approves a production tag.

```bash
just app-promote-prod app=jobbot3000 tag=main-REPLACE_SHORTSHA
```

Verify production after promotion:

```bash
just app-status app=jobbot3000 env=prod
```

```bash
just app-verify app=jobbot3000 env=prod
```

## Rollback

Rollback by redeploying a previous immutable image tag that is still present in GHCR and compatible with the pinned chart.

```bash
just app-redeploy app=jobbot3000 env=prod tag=main-PREVIOUSSHA
```

If the chart pin itself must roll back, first confirm the old chart still exists in GHCR, then update `docs/apps/jobbot3000.version` through the same review process used for chart bumps.
