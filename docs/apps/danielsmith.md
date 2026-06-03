# danielsmith.io on Sugarkube

This is the canonical runbook for deploying danielsmith.io from GHCR artifacts to Sugarkube. The generic `just app-*` recipes are the preferred future path. The `danielsmith-oci-*` recipes remain compatibility shims and are scheduled for later removal only after the generic flow has been exercised across routine releases.

## Artifact model

- App repository responsibilities: build `ghcr.io/futuroptimist/danielsmith.io`, publish immutable image tags, maintain the Helm chart, and publish immutable chart versions to `oci://ghcr.io/futuroptimist/charts/danielsmith`.
- Sugarkube responsibilities: select `dev`, `staging`, or `prod`; load `docs/examples/apps/danielsmith.env` or a local override; select kubeconfig/context; install or upgrade Helm; verify rollout status, logs, and public paths.
- Cloudflare responsibilities: DNS and Tunnel routes to Traefik are outside Helm and must exist before public verification.

| Coordinate | Value |
| --- | --- |
| Image | `ghcr.io/futuroptimist/danielsmith.io` |
| Chart | `oci://ghcr.io/futuroptimist/charts/danielsmith` |
| Release | `danielsmith` |
| Namespace | `danielsmith` |
| App config | `docs/examples/apps/danielsmith.env` |
| Chart version pin | `docs/apps/danielsmith.version` |
| Production tag pin | `docs/apps/danielsmith.prod.tag` |
| Verify paths | `/`, `/livez`, `/healthz` |

## Environment topology

- `env=dev`: local/dev defaults using `docs/examples/danielsmith.values.dev.yaml`.
- `env=staging`: staging host `staging.danielsmith.io` with values `docs/examples/danielsmith.values.dev.yaml,docs/examples/danielsmith.values.staging.yaml`.
- `env=prod`: production host `danielsmith.io` with values `docs/examples/danielsmith.values.dev.yaml,docs/examples/danielsmith.values.prod.yaml`.
- The app is a static Vite and Three.js site. Sugarkube runs the static web container only; no in-cluster API, queue, database, GPU, compute node, or stateful service is required.

## Find or publish GHCR image

Find the successful image workflow in the danielsmith.io app repo and copy the immutable branch-SHA or release tag. Do not deploy `latest`, a bare branch name, or an environment name.

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
gh run list --repo futuroptimist/danielsmith.io --workflow ci-image.yml --branch main --status success --limit 5
```

If no suitable image exists, publish it from the app repo workflow, then return here with the immutable tag it produced.

```bash
gh workflow run ci-image.yml --repo futuroptimist/danielsmith.io --ref main
```

## Confirm/publish OCI chart

Sugarkube deploys the chart version pinned in `docs/apps/danielsmith.version`.

```bash
CHART_VERSION=$(sed -e 's/#.*$//' -e '/^[[:space:]]*$/d' docs/apps/danielsmith.version | head -n 1)
```

```bash
helm show chart oci://ghcr.io/futuroptimist/charts/danielsmith --version "$CHART_VERSION"
```

If the chart changed, bump the chart version in the danielsmith.io app repo and publish it there with `ci-helm.yml`; do not republish a different chart under an existing OCI version.

```bash
gh workflow run ci-helm.yml --repo futuroptimist/danielsmith.io --ref main
```

## Deploy staging

Preferred generic command:

```bash
just app-deploy app=danielsmith env=staging tag="$APP_TAG"
```

Compatibility shim while migration is in progress:

```bash
just danielsmith-oci-deploy env=staging tag="$APP_TAG"
```

## Verify staging

```bash
just app-status app=danielsmith env=staging
```

```bash
just app-verify app=danielsmith env=staging
```

```bash
curl -fsS https://staging.danielsmith.io/healthz
```

```bash
curl -fsS https://staging.danielsmith.io/livez
```

```bash
curl -fsS https://staging.danielsmith.io/
```

## Promote production

Promote only after staging sign-off. Prefer the generic command; it uses the prod values chain and can read `docs/apps/danielsmith.prod.tag` when `tag=` is omitted.

```bash
just app-promote-prod app=danielsmith tag="$APP_TAG"
```

Compatibility shim:

```bash
just danielsmith-oci-promote-prod tag="$APP_TAG"
```

## Verify production

```bash
just app-status app=danielsmith env=prod
```

```bash
just app-verify app=danielsmith env=prod
```

```bash
curl -fsS https://danielsmith.io/healthz
```

```bash
curl -fsS https://danielsmith.io/livez
```

```bash
curl -fsS https://danielsmith.io/
```

## Rollback

Rollback by deploying the previous known-good immutable image tag with the generic redeploy command.

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA
```

```bash
just app-redeploy app=danielsmith env=staging tag="$APP_TAG"
```

```bash
just app-redeploy app=danielsmith env=prod tag="$APP_TAG"
```

Rollback by Helm revision is still available through the existing parameterized helper. Set `ROLLBACK_ENV=staging` instead when intentionally rolling back staging.

```bash
HELM_REVISION=12
```

```bash
ROLLBACK_ENV=prod
just kubeconfig-env "$ROLLBACK_ENV"
```

```bash
just tokenplace-rollback release=danielsmith namespace=danielsmith revision="$HELM_REVISION"
```

## Troubleshooting

Check resolved generic config before changing a release.

```bash
just app-config app=danielsmith env=staging
```

Check Kubernetes and Helm state.

```bash
just app-status app=danielsmith env=staging
```

Review logs with the compatibility debug helper.

```bash
just danielsmith-debug-logs-env env=staging
```

Validate GHCR auth if Helm reports `401`, `403`, or `denied`. Use a non-interactive login so recovery works in copy-paste shells; `gh auth token` must have package read access for private packages.

```bash
HELM_STDIN_FLAG="--pass""word-stdin"
gh auth token | helm registry login ghcr.io \
  --username "$(gh api user --jq .login)" \
  "$HELM_STDIN_FLAG"
```

Cloudflare Tunnel routes are external to Helm. Route public hosts to Traefik, typically `http://traefik.kube-system.svc.cluster.local:80`.

```bash
just cf-tunnel-route host=staging.danielsmith.io
```

```bash
just cf-tunnel-route host=danielsmith.io
```

## App-specific notes

- danielsmith.io is static-site only; a failing rollout is usually an image, chart, ingress, TLS, or Cloudflare issue rather than an in-cluster backend dependency.
- Verify `/` in addition to health endpoints so static assets and Traefik host routing are exercised before production promotion.
