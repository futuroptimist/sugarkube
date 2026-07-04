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
- `env=staging`: values chain `docs/examples/jobbot3000.values.dev.yaml,docs/examples/jobbot3000.values.staging.yaml`; real host `staging.jobbot3000.tech`.
- `env=prod`: values chain `docs/examples/jobbot3000.values.dev.yaml,docs/examples/jobbot3000.values.prod.yaml`; placeholder host `jobbot3000.example.test`.

The committed staging overlay uses the real first-rollout hostname `staging.jobbot3000.tech`, matching the existing Sugarkube pattern for staging apps. Keep Cloudflare DNS and Tunnel routing outside Helm; for this first staging deployment the Cloudflare Tunnel/Connector route for `staging.jobbot3000.tech` path `*` must point at `http://traefik.kube-system.svc.cluster.local:80`. Production remains placeholder-only until a later explicit promotion approval updates the production overlay and `docs/apps/jobbot3000.prod.tag`.

## Find or publish GHCR image

Find the successful image workflow in the jobbot3000 app repo and copy the immutable branch-SHA or release tag. Do not deploy `latest`, `main-latest`, a bare branch name, or an environment name.

Web UI shortcuts:

- Open [recent image workflow runs](https://github.com/futuroptimist/jobbot3000/actions/workflows/ci-image.yml) or [successful main image runs](https://github.com/futuroptimist/jobbot3000/actions/workflows/ci-image.yml?query=branch%3Amain+is%3Asuccess).
- Open [GHCR image package versions](https://github.com/futuroptimist/jobbot3000/pkgs/container/jobbot3000).
- Copy the immutable tag from a successful workflow summary or package version.

```bash
APP_TAG=main-b3e6df1a4f68
```

## Confirm/publish OCI chart

Sugarkube deploys the chart version pinned in `docs/apps/jobbot3000.version`. Use [recent chart workflow runs](https://github.com/futuroptimist/jobbot3000/actions/workflows/ci-helm.yml), [GHCR chart package versions](https://github.com/futuroptimist/jobbot3000/pkgs/container/charts%2Fjobbot3000), and [the chart source](https://github.com/futuroptimist/jobbot3000/tree/main/charts/jobbot3000) to confirm the pinned immutable version.

```bash
just app-chart-status app=jobbot3000
```

The initial staging candidate `main-b3e6df1a4f68` was checked against GHCR before being baked into this runbook. Re-check it before deploy if the package visibility or retention policy changes.
```bash
python3 scripts/app_config.py validate-tag main-b3e6df1a4f68
curl -fsSL -H "Authorization: Bearer $(curl -fsSL 'https://ghcr.io/token?service=ghcr.io&scope=repository:futuroptimist/jobbot3000:pull' | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')" \
  -H 'Accept: application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json' \
  https://ghcr.io/v2/futuroptimist/jobbot3000/manifests/main-b3e6df1a4f68 >/dev/null
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

### First staging rollout command path

The following path is copy-paste-ready for the first real staging deployment at `https://staging.jobbot3000.tech` and preserves the generic `just app-*` deployment surface:

```bash
just app-config app=jobbot3000 env=staging
just app-chart-status app=jobbot3000
just app-deploy app=jobbot3000 env=staging tag=main-b3e6df1a4f68
just app-status app=jobbot3000 env=staging
just app-verify app=jobbot3000 env=staging
```

`just app-verify` must continue to verify exactly `/`, `/healthz`, and `/livez`.

```bash
just app-deploy app=jobbot3000 env=staging tag=main-b3e6df1a4f68
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
just app-redeploy app=jobbot3000 env=staging tag=main-b3e6df1a4f68
```

Production promotion is explicitly blocked until staging is verified and a separate production approval records the approved tag in `docs/apps/jobbot3000.prod.tag`. Do not run this yet; when approval exists, promote using the exact immutable image tag that passed staging:

```bash
just app-promote-prod app=jobbot3000 tag=main-APPROVED_SHORTSHA
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

## Debugging staging failures

Use these commands to separate DNS/Tunnel, Ingress, image, chart, and certificate issues without adding secrets to the repo.

```bash
# Confirm the public hostname resolves and reaches Cloudflare.
dig +short staging.jobbot3000.tech
curl -I https://staging.jobbot3000.tech/

# Confirm the Cloudflare Tunnel route outside Helm points path * at Traefik.
# In the Cloudflare dashboard, verify staging.jobbot3000.tech -> http://traefik.kube-system.svc.cluster.local:80.

# Inspect Traefik-facing Kubernetes objects and rollout state.
kubectl -n jobbot3000 get ingress,svc,deploy,pods
kubectl -n jobbot3000 describe ingress jobbot3000
kubectl -n jobbot3000 logs deploy/jobbot3000 --tail=100

# Confirm Helm used the pinned chart and immutable image tag.
helm -n jobbot3000 get values jobbot3000
helm -n jobbot3000 status jobbot3000

# Confirm GHCR artifacts are reachable from the operator workstation.
just app-chart-status app=jobbot3000
python3 scripts/app_config.py validate-tag main-b3e6df1a4f68

# Inspect cert-manager if HTTPS is failing after Ingress exists.
kubectl -n jobbot3000 get certificate,certificaterequest,order,challenge
kubectl -n jobbot3000 describe certificate jobbot3000-staging-tls
kubectl -n cert-manager logs deploy/cert-manager --tail=100
```
