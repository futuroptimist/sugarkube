# jobbot3000 Sugarkube runbook

jobbot3000 is deployed through Sugarkube's generic app recipes. The
jobbot3000 repository owns the Dockerfile, static image, Helm chart, chart
publication, app defaults, and release docs. Sugarkube owns the cluster-facing
configuration: sanitized example app config, values overlays, chart pins,
production tag pins, deploy/status/verify commands, and this runbook.

## Artifact discovery

- App repository: <https://github.com/futuroptimist/jobbot3000>
- Image workflow: <https://github.com/futuroptimist/jobbot3000/blob/main/.github/workflows/ci-image.yml>
- GHCR image package: <https://github.com/futuroptimist/jobbot3000/pkgs/container/jobbot3000>
- Chart workflow: <https://github.com/futuroptimist/jobbot3000/blob/main/.github/workflows/ci-helm.yml>
- GHCR chart package: <https://github.com/futuroptimist/jobbot3000/pkgs/container/charts%2Fjobbot3000>
- Dockerfile source: <https://github.com/futuroptimist/jobbot3000/blob/main/Dockerfile>
- Helm chart source: <https://github.com/futuroptimist/jobbot3000/tree/main/charts/jobbot3000>
- Image release docs: <https://github.com/futuroptimist/jobbot3000/blob/main/docs/release-ghcr.md>
- Helm release docs: <https://github.com/futuroptimist/jobbot3000/blob/main/docs/release-helm.md>

Sugarkube consumes:

- Image: `ghcr.io/futuroptimist/jobbot3000`
- Chart: `oci://ghcr.io/futuroptimist/charts/jobbot3000`
- Chart pin: [`jobbot3000.version`](jobbot3000.version)
- Production tag pin: [`jobbot3000.prod.tag`](jobbot3000.prod.tag)
- Example app config: [`../examples/apps/jobbot3000.env`](../examples/apps/jobbot3000.env)

## Data, backup, and seeding model

jobbot3000 is a static browser-only application. Kubernetes serves the web app;
it does not store job applications, outreach messages, interview notes, offers,
outcomes, imported files, contacts, resume links, Drive links, or private user
settings.

Private user data lives in the user's browser IndexedDB. Seed and restore data
manually through the browser UI after opening the deployed app:

- CSV is the spreadsheet-compatible, human-editable backup format.
- JSON and NDJSON are full-fidelity backup and restore formats.
- Dev, staging, and production are seeded only by browser import.

Do not bake real user data into images, charts, Helm values, Kubernetes
Secrets, ConfigMaps, PVCs, Sugarkube docs, or Sugarkube examples. The example
values intentionally avoid PVCs and server-side persistence.

## Staging deploy

Pick an immutable image tag from the jobbot3000 image workflow or GHCR package,
then deploy it to staging:

```bash
just app-deploy app=jobbot3000 env=staging tag=main-REPLACE_SHORTSHA
```

Redeploy the same or another immutable tag when re-running a rollout:

```bash
just app-redeploy app=jobbot3000 env=staging tag=main-REPLACE_SHORTSHA
```

## Status and verification

Inspect the Helm release and resolved ingress host:

```bash
just app-status app=jobbot3000 env=staging
```

Run the generic HTTP smoke checks. The configured paths are `/`, `/healthz`, and
`/livez`:

```bash
just app-verify app=jobbot3000 env=staging
```

Preview the verification curls without making network requests:

```bash
just app-verify app=jobbot3000 env=staging print_only=1
```

## Chart pin operations

Before the first deploy, and before release deploys, confirm the committed chart
pin exists in GHCR. This is especially important when the operator environment
cannot run `helm show chart` during review:

```bash
just app-chart-status app=jobbot3000
helm show chart oci://ghcr.io/futuroptimist/charts/jobbot3000 --version 0.1.0
```

When jobbot3000 publishes a new chart version that Sugarkube should consume,
bump the committed pin intentionally:

```bash
just app-chart-bump app=jobbot3000 version=0.1.1
```

Do not use mutable chart selectors. Chart bumps are separate from image tag
promotion and should be committed as explicit pin changes.

## Production promotion

Promote only an immutable image tag that already passed staging, such as a
branch-SHA tag from the image workflow:

```bash
just app-promote-prod app=jobbot3000 tag=main-REPLACE_SHORTSHA
```

Do not use `latest`, `main-latest`, bare branch names, or environment names as
production tags. Update [`jobbot3000.prod.tag`](jobbot3000.prod.tag) only when an
immutable image tag is approved as the production pin.

## Rollback

Rollback by redeploying a previously known-good immutable image tag. If the
chart pin also changed, revert or bump [`jobbot3000.version`](jobbot3000.version)
first, then redeploy:

```bash
just app-redeploy app=jobbot3000 env=prod tag=main-PREVIOUSSHA
```

After rollback, run:

```bash
just app-status app=jobbot3000 env=prod
just app-verify app=jobbot3000 env=prod
```
