# democratized.space (dspace) on Sugarkube

This is the canonical runbook for deploying DSPACE from GHCR artifacts to Sugarkube. The generic `just app-*` recipes are the preferred future path. The `dspace-oci-*` recipes remain compatibility shims and are scheduled for later removal only after the generic flow has been exercised across routine releases.

## Artifact model

- App repository responsibilities: build `ghcr.io/democratizedspace/dspace`, publish immutable image tags, maintain the Helm chart, and publish immutable chart versions to `oci://ghcr.io/democratizedspace/charts/dspace`.
- Sugarkube responsibilities: select `dev`, `staging`, or `prod`; load `docs/examples/apps/dspace.env` or a local override; select kubeconfig/context; install or upgrade Helm; verify rollout status, logs, and public paths.
- Cloudflare responsibilities: DNS and Tunnel routes to Traefik are outside Helm and must exist before public verification.

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

### Artifact links

Use these links before changing a deployment so the workflow runs, package versions, and source paths all agree.

| Artifact | Link |
| --- | --- |
| App repository | [DSPACE app repository](https://github.com/democratizedspace/dspace) |
| Image workflow | [Recent image workflow runs](https://github.com/democratizedspace/dspace/actions/workflows/ci-image.yml) |
| Successful main image runs | [Successful main image workflow runs](https://github.com/democratizedspace/dspace/actions/workflows/ci-image.yml?query=branch%3Amain+is%3Asuccess) |
| Successful v3 image runs | [Successful v3 image workflow runs](https://github.com/democratizedspace/dspace/actions/workflows/ci-image.yml?query=branch%3Av3+is%3Asuccess) |
| GHCR image package | [GHCR image package versions](https://github.com/democratizedspace/dspace/pkgs/container/dspace) |
| Chart workflow | [Recent chart workflow runs](https://github.com/democratizedspace/dspace/actions/workflows/ci-helm.yml) |
| GHCR chart package | No public package page is associated yet; use the [DSPACE chart package lookup](https://github.com/orgs/democratizedspace/packages?repo_name=dspace&q=charts%2Fdspace) and `helm show chart` below until the chart package appears. |
| Dockerfile | [Application Dockerfile](https://github.com/democratizedspace/dspace/blob/main/Dockerfile) |
| Chart source | [Helm chart source](https://github.com/democratizedspace/dspace/tree/main/charts/dspace) |
| App release guide | [Sugarkube release guide in the app repo](https://github.com/democratizedspace/dspace/blob/main/docs/ops/sugarkube-release.md) |

## Environment topology

- `env=dev`: future single-node/non-HA environment using `docs/examples/dspace.values.dev.yaml`.
  The dev overlay intentionally does not choose a token.place origin; developers who need local runtime routing can copy `docs/examples/apps/dspace.env` to a local app config and add chart-supported `env` entries to their private values file.
- `env=staging`: HA staging on the staging Sugarkube cluster with host `staging.democratized.space` and values `docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml`.
  The staging overlay injects `DSPACE_TOKEN_PLACE_URL=https://staging.token.place` and `DSPACE_TOKEN_PLACE_CHAT_MODEL=gpt-5-chat-latest`.
- `env=prod`: HA production on the production Sugarkube cluster with host `democratized.space` and values `docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.prod.yaml`.
  The production overlay injects `DSPACE_TOKEN_PLACE_URL=https://token.place` and `DSPACE_TOKEN_PLACE_CHAT_MODEL=gpt-5-chat-latest`.
- Optional legacy/canary host `prod.democratized.space` still has `docs/examples/dspace.values.prod-subdomain.yaml`, but the generic app flow uses the production apex overlay unless a local app config intentionally overrides it.

## Find or publish GHCR image

Find the successful image workflow in the DSPACE app repo and copy the immutable branch-SHA or release tag. The GitHub Actions workflow page is where recent builds are found; the GHCR package page is where published image tags are cross-checked. Do not deploy `latest`, a bare branch name, or an environment name.

Web UI shortcuts:

- Open [recent image workflow runs](https://github.com/democratizedspace/dspace/actions/workflows/ci-image.yml), [successful main image runs](https://github.com/democratizedspace/dspace/actions/workflows/ci-image.yml?query=branch%3Amain+is%3Asuccess), or [successful v3 image runs](https://github.com/democratizedspace/dspace/actions/workflows/ci-image.yml?query=branch%3Av3+is%3Asuccess).
  Consult `v3` in addition to `main` because the Raspberry Pi bootstrap helper still defaults `DSPACE_BRANCH` to `v3` for current DSPACE clones.
- Open [GHCR image package versions](https://github.com/democratizedspace/dspace/pkgs/container/dspace).
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

Sugarkube deploys the chart version pinned in `docs/apps/dspace.version`. Use [recent chart workflow runs](https://github.com/democratizedspace/dspace/actions/workflows/ci-helm.yml) to find chart publish attempts, `helm show chart` below to confirm available immutable chart versions, and [the chart source](https://github.com/democratizedspace/dspace/tree/main/charts/dspace) to review the chart content that should match the pinned version. The DSPACE OCI chart does not currently have an associated public GHCR package page; check the [DSPACE chart package lookup](https://github.com/orgs/democratizedspace/packages?repo_name=dspace&q=charts%2Fdspace) until that package page appears.

```bash
CHART_VERSION=$(sed -e 's/#.*$//' -e '/^[[:space:]]*$/d' docs/apps/dspace.version | head -n 1)
```

```bash
helm show chart oci://ghcr.io/democratizedspace/charts/dspace --version "$CHART_VERSION"
```

If the chart changed, bump the chart version in the DSPACE app repo and publish it there with [the chart workflow](https://github.com/democratizedspace/dspace/actions/workflows/ci-helm.yml); do not republish a different chart under an existing OCI version.

```bash
gh workflow run ci-helm.yml --repo democratizedspace/dspace --ref main
```

## Deploy staging

After this repository change is merged, deploy the new immutable, environment-neutral DSPACE image that contains runtime `/config.json` support. The image tag stays the same as it moves between staging and production; the Sugarkube values overlays, not image names, select the token.place origin.

Preferred generic command:

```bash
just app-deploy app=dspace env=staging tag="$APP_TAG"
```

Compatibility shim while migration is in progress:

```bash
just dspace-oci-deploy env=staging tag="$APP_TAG"
```

## Verify staging

Generic verification discovers the host from Helm values or Ingress, executes the configured DSPACE paths, prints a per-path body preview, and exits non-zero if any HTTP check fails. It does not validate the `/config.json` body, so staging sign-off also requires the explicit `curl | jq` routing gate below. Use `print_only=1` when you only want the curl commands for docs or troubleshooting.

```bash
just app-status app=dspace env=staging
```

```bash
just app-verify app=dspace env=staging
```

```bash
just app-verify app=dspace env=staging print_only=1
```

The runtime config check is a required routing gate, not an optional fallback: it must return the staging token.place origin before production promotion and before opening `/chat`. Browser Network must show staging DSPACE calling staging token.place; a staging request to production token.place is a stop-ship routing failure. If `/chat` fails after `/config.json` is correct, capture the browser CORS error plus the token.place response headers and escalate to the token.place operator; do not change DSPACE values to work around token.place CORS policy.

```bash
curl -fsS https://staging.democratized.space/config.json \
  | jq -e '
      .tokenPlace.url == "https://staging.token.place"
      and .tokenPlace.model == "gpt-5-chat-latest"
    '
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

Print the generated curl commands without executing them when you need a manual fallback:

```bash
just app-verify app=dspace env=prod print_only=1
```

The runtime config check is a required production routing gate before opening `/chat`; browser Network should show production DSPACE calling production token.place. The immutable DSPACE image remains environment-neutral, and this production overlay selects the production token.place origin without rebuilding the image. If `/chat` fails after `/config.json` is correct, capture the browser CORS error plus the token.place response headers and escalate to the token.place operator; do not change DSPACE values to work around token.place CORS policy.

```bash
curl -fsS https://democratized.space/config.json \
  | jq -e '
      .tokenPlace.url == "https://token.place"
      and .tokenPlace.model == "gpt-5-chat-latest"
    '
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

- DSPACE serves `/config.json`; verify it with `jq` before production promotion and before opening `/chat`.
- Keep release lineage separate from environment routing: image tags identify app code, values overlays identify `staging` or `prod` hostnames and token.place origins.
- The optional `prod.democratized.space` overlay is not the default production path in the generic config.

### Legacy Helm helper reference

The generic app commands above should be the normal operator path. Keep these lower-level helpers available for compatibility with existing tests and older runbooks when debugging raw Helm parameters.

```bash
just helm-oci-install release=dspace namespace=dspace chart=oci://ghcr.io/democratizedspace/charts/dspace values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml version_file=docs/apps/dspace.version tag="$APP_TAG"
```

```bash
just helm-oci-upgrade release=dspace namespace=dspace chart=oci://ghcr.io/democratizedspace/charts/dspace values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml version_file=docs/apps/dspace.version tag="$APP_TAG"
```
