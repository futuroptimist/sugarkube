# jobbot3000 Sugarkube runbook

jobbot3000 is a static, browser-only job application tracker. Sugarkube only
orchestrates the Kubernetes deployment of the published static image and OCI Helm
chart; the jobbot3000 repository owns the Dockerfile, image workflow, chart,
chart publishing, and app release documentation.

### Artifact links

| Artifact | Link |
| --- | --- |
| app repository | <https://github.com/futuroptimist/jobbot3000> |
| image workflow | <https://github.com/futuroptimist/jobbot3000/actions/workflows/ci-image.yml> |
| GHCR image package | <https://github.com/futuroptimist/jobbot3000/pkgs/container/jobbot3000> |
| chart workflow | <https://github.com/futuroptimist/jobbot3000/actions/workflows/ci-helm.yml> |
| GHCR chart package | <https://github.com/futuroptimist/jobbot3000/pkgs/container/charts%2Fjobbot3000> |
| Dockerfile | <https://github.com/futuroptimist/jobbot3000/blob/main/Dockerfile> |
| chart source path | <https://github.com/futuroptimist/jobbot3000/tree/main/charts/jobbot3000> |
| image release guide | <https://github.com/futuroptimist/jobbot3000/blob/main/docs/release-ghcr.md> |
| Helm release guide | <https://github.com/futuroptimist/jobbot3000/blob/main/docs/release-helm.md> |

Web UI shortcuts: open the image workflow, the GHCR image package, the chart
workflow, and the GHCR chart package before deploying so the image tag and chart
version are copied from successful app-repo artifacts instead of guessed.

## Deployment coordinates

- App config: `docs/examples/apps/jobbot3000.env`
- Release/namespace: `jobbot3000` / `jobbot3000`
- Image: `ghcr.io/futuroptimist/jobbot3000`
- Chart: `oci://ghcr.io/futuroptimist/charts/jobbot3000`
- Chart pin: `docs/apps/jobbot3000.version`
- Production tag pin placeholder: `docs/apps/jobbot3000.prod.tag`
- Container/service port: `8080`
- Generic verify paths: `/`, `/healthz`, `/livez`

If this Codex environment could not run `helm show chart`, operators should
confirm the pinned chart exists before the first deploy:

```bash
just app-chart-status app=jobbot3000
```

or:

```bash
helm show chart oci://ghcr.io/futuroptimist/charts/jobbot3000 --version 0.1.0
```

## Staging deploy

Pick an immutable image tag from a successful jobbot3000 image workflow, such as
`main-REPLACE_SHORTSHA`. Do not deploy `latest`, `main-latest`, a bare branch
name, or an environment name.

```bash
just app-deploy app=jobbot3000 env=staging tag=main-REPLACE_SHORTSHA
```

Redeploy the same immutable tag after values, ingress, TLS, or cluster recovery:

```bash
just app-redeploy app=jobbot3000 env=staging tag=main-REPLACE_SHORTSHA
```

Check rollout state:

```bash
just app-status app=jobbot3000 env=staging
```

Run generic HTTP smoke checks:

```bash
just app-verify app=jobbot3000 env=staging
```

Print the generated checks without curling the host:

```bash
just app-verify app=jobbot3000 env=staging print_only=1
```

## Chart operations

Inspect the currently pinned chart and the latest published GHCR chart metadata:

```bash
just app-chart-status app=jobbot3000
```

After the jobbot3000 repository publishes a new immutable chart version, bump the
Sugarkube chart pin explicitly:

```bash
just app-chart-bump app=jobbot3000 version=0.1.0
```

Commit the resulting `docs/apps/jobbot3000.version` change with the rest of the
release coordination. Never use a mutable chart selector for staging or
production.

## Production promotion and rollback

Promote production only with the same immutable image tag that passed staging:

```bash
just app-promote-prod app=jobbot3000 tag=main-REPLACE_SHORTSHA
```

Rollback by redeploying a previous known-good immutable image tag:

```bash
just app-redeploy app=jobbot3000 env=prod tag=main-REPLACE_PREVIOUS_SHORTSHA
```

Use Helm revision rollback only when you intentionally want the entire rendered
release state from a previous revision, not just the previous image.

## Browser-local data model

jobbot3000 stores private user data in the browser's IndexedDB. The Kubernetes
workload serves static files only; it does not own job applications, outreach
messages, interviews, offers, outcomes, notes, contacts, resume links, Drive
links, imported spreadsheets, backups, or private settings.

Backup and restore expectations:

- CSV is the spreadsheet-compatible, human-editable backup format.
- JSON and NDJSON are full-fidelity backup/restore formats.
- Dev, staging, and production seeding happens manually through the browser
  import UI after the static app is deployed.
- Do not bake real user data into Docker images, Helm charts, Helm values,
  Kubernetes Secrets, ConfigMaps, PVCs, repo fixtures, or Sugarkube docs/examples.

The example values intentionally configure no PVCs and no Secret- or
ConfigMap-backed user-data persistence. If a future jobbot3000 feature needs
server-side state, update the app repository contract first, then add a focused
Sugarkube follow-up instead of changing these static-app examples in place.
