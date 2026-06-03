# democratized.space (dspace) on Sugarkube

This is the canonical runbook for deploying DSPACE from GHCR artifacts to Sugarkube. The generic `just app-*` recipes are the preferred future path. The `dspace-oci-*` recipes remain compatibility shims and are scheduled for later removal only after the generic flow has been exercised across routine releases.

## Artifact model

- App repository responsibilities: build `ghcr.io/democratizedspace/dspace`, publish immutable image tags, maintain the Helm chart, and publish immutable chart versions to `oci://ghcr.io/democratizedspace/charts/dspace`.
- Sugarkube responsibilities: select `dev`, `staging`, or `prod`; load `docs/examples/apps/dspace.env` or a local override; select kubeconfig/context; install or upgrade Helm; verify rollout status, logs, and public paths.
- Cloudflare responsibilities: DNS and Tunnel routes to Traefik are outside Helm and must exist before public verification.

### Artifact links

| Artifact | Link |
| --- | --- |
| App repo | [DSPACE source repository](https://github.com/democratizedspace/dspace) |
| Image workflow | [DSPACE image workflow recent runs](https://github.com/democratizedspace/dspace/actions/workflows/ci-image.yml) and [successful `main` image runs](https://github.com/democratizedspace/dspace/actions/workflows/ci-image.yml?query=branch%3Amain+is%3Asuccess) and [successful `v3` image runs](https://github.com/democratizedspace/dspace/actions/workflows/ci-image.yml?query=branch%3Av3+is%3Asuccess) remain useful while DSPACE release work still references the `v3` branch |
| GHCR image package | [DSPACE image package versions](https://github.com/democratizedspace/dspace/pkgs/container/dspace) |
| Chart workflow | [DSPACE chart publish workflow runs](https://github.com/democratizedspace/dspace/actions/workflows/ci-helm.yml) |
| GHCR chart package | [DSPACE chart package versions](https://github.com/orgs/democratizedspace/packages?ecosystem=container&repo_name=dspace) |
| Dockerfile | [DSPACE Dockerfile](https://github.com/democratizedspace/dspace/blob/main/Dockerfile) |
| Chart source | [DSPACE Helm chart source](https://github.com/democratizedspace/dspace/tree/main/charts/dspace) |
| App release guide | [DSPACE Sugarkube release guide](https://github.com/democratizedspace/dspace/blob/main/docs/ops/sugarkube-release.md) |

The DSPACE chart workflow publishes `oci://ghcr.io/democratizedspace/charts/dspace`; GitHub currently exposes the openable package discovery page as the democratizedspace container package listing filtered to the DSPACE repo.

| Coordinate | Value |
| --- | --- |
| Image | `ghcr.io/democratizedspace/dspace` |
| Chart | `oci://ghcr.io/democratizedspace/charts/dspace` |
| Release | `dspace` |
| Namespace | `dspace` |
| App config | `docs/examples/apps/dspace.env` |
| Chart version pin | `docs/apps/dspace.version` |
| Production tag pin | `docs/apps/dspace.prod.tag` |
| Verify paths | `/config.json`, `/healthz`, `/livez` |

## Environment topology

- `env=dev`: future single-node/non-HA environment using `docs/examples/dspace.values.dev.yaml`.
- `env=staging`: HA staging on the staging Sugarkube cluster with host `staging.democratized.space` and values `docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml`.
- `env=prod`: HA production on the production Sugarkube cluster with host `democratized.space` and values `docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.prod.yaml`.
- Optional legacy/canary host `prod.democratized.space` still has `docs/examples/dspace.values.prod-subdomain.yaml`, but the generic app flow uses the production apex overlay unless a local app config intentionally overrides it.

## Find or publish GHCR image

Find the successful image workflow in the DSPACE app repo and copy the immutable branch-SHA or release tag. Do not deploy `latest`, a bare branch name, or an environment name.

Web UI shortcuts before using `gh`:

- Open the [DSPACE image workflow recent runs](https://github.com/democratizedspace/dspace/actions/workflows/ci-image.yml); GitHub Actions is where recent image builds and workflow summaries are found.
- Open the [DSPACE GHCR image package versions](https://github.com/democratizedspace/dspace/pkgs/container/dspace); GHCR is where published package tags are cross-checked.
- Copy the immutable tag from a successful workflow summary or package version.

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
gh run list --repo democratizedspace/dspace --workflow ci-image.yml --branch main --status success --limit 5
```

If no suitable image exists, publish it from the app repo workflow, then return here with the immutable tag it produced.

```bash
gh workflow run ci-image.yml --repo democratizedspace/dspace --ref main
```

## Confirm/publish OCI chart

Sugarkube deploys the chart version pinned in `docs/apps/dspace.version`.

```bash
CHART_VERSION=$(sed -e 's/#.*$//' -e '/^[[:space:]]*$/d' docs/apps/dspace.version | head -n 1)
```

```bash
helm show chart oci://ghcr.io/democratizedspace/charts/dspace --version "$CHART_VERSION"
```

Chart discovery shortcuts:

- Open the [DSPACE chart publish workflow runs](https://github.com/democratizedspace/dspace/actions/workflows/ci-helm.yml); GitHub Actions is where recent chart publish attempts and failures are found.
- Open the [DSPACE GHCR chart package listing](https://github.com/orgs/democratizedspace/packages?ecosystem=container&repo_name=dspace); chart package pages confirm available immutable chart versions for `oci://ghcr.io/democratizedspace/charts/dspace` when GitHub exposes the chart package publicly.
- Review the [DSPACE Helm chart source](https://github.com/democratizedspace/dspace/tree/main/charts/dspace) before publishing a chart change.

If the chart changed, bump the chart version in the DSPACE app repo and publish it there with `ci-helm.yml`; do not republish a different chart under an existing OCI version.

```bash
gh workflow run ci-helm.yml --repo democratizedspace/dspace --ref main
```

## Deploy staging

Preferred generic command:

```bash
just app-deploy app=dspace env=staging tag="$APP_TAG"
```

Compatibility shim while migration is in progress:

```bash
just dspace-oci-deploy env=staging tag="$APP_TAG"
```

## Verify staging

Generic verification discovers the host from Helm values or Ingress and checks the configured DSPACE paths.

```bash
just app-status app=dspace env=staging
```

```bash
just app-verify app=dspace env=staging
```

Manual public checks are useful when Cloudflare or cert-manager are suspect.

```bash
curl -fsS https://staging.democratized.space/config.json | jq .
```

```bash
curl -fsS https://staging.democratized.space/healthz
```

```bash
curl -fsS https://staging.democratized.space/livez
```

## Promote production

Promote only after staging sign-off. Prefer the generic command; it uses the prod values chain and can read `docs/apps/dspace.prod.tag` when `tag=` is omitted.

```bash
just app-promote-prod app=dspace tag="$APP_TAG"
```

Compatibility shim:

```bash
just dspace-oci-promote-prod tag="$APP_TAG"
```

## Verify production

```bash
just app-status app=dspace env=prod
```

```bash
just app-verify app=dspace env=prod
```

```bash
curl -fsS https://democratized.space/config.json | jq .
```

```bash
curl -fsS https://democratized.space/healthz
```

```bash
curl -fsS https://democratized.space/livez
```

## Rollback

Rollback by deploying the previous known-good immutable image tag with the generic redeploy command.

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA
```

```bash
just app-redeploy app=dspace env=staging tag="$APP_TAG"
```

```bash
just app-redeploy app=dspace env=prod tag="$APP_TAG"
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
just tokenplace-rollback release=dspace namespace=dspace revision="$HELM_REVISION"
```

## Troubleshooting

Check resolved generic config before changing a release.

```bash
just app-config app=dspace env=staging
```

Check Kubernetes and Helm state.

```bash
just app-status app=dspace env=staging
```

Review logs with the compatibility debug helper.

```bash
just dspace-debug-logs-env env=staging
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
just cf-tunnel-route host=staging.democratized.space
```

```bash
just cf-tunnel-route host=democratized.space
```

## App-specific notes

- DSPACE serves `/config.json`; verify it with `jq` before production promotion.
- Keep release lineage separate from environment routing: image tags identify app code, values overlays identify `staging` or `prod` hostnames.
- The optional `prod.democratized.space` overlay is not the default production path in the generic config.

### Legacy Helm helper reference

The generic app commands above should be the normal operator path. Keep these lower-level helpers available for compatibility with existing tests and older runbooks when debugging raw Helm parameters.

```bash
just helm-oci-install release=dspace namespace=dspace chart=oci://ghcr.io/democratizedspace/charts/dspace values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml version_file=docs/apps/dspace.version tag="$APP_TAG"
```

```bash
just helm-oci-upgrade release=dspace namespace=dspace chart=oci://ghcr.io/democratizedspace/charts/dspace values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml version_file=docs/apps/dspace.version tag="$APP_TAG"
```
