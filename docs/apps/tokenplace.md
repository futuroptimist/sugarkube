# token.place on Sugarkube

Use this runbook for GHCR-first token.place relay deploys, promotions,
verification, and rollback on Sugarkube. The preferred future path is the generic
app flow backed by `docs/examples/apps/tokenplace.env`; the `tokenplace-*`
recipes remain compatibility shims until the generic flow has been exercised
across routine releases.

## 1. Artifact model

- App repository responsibility: build and publish
  `ghcr.io/futuroptimist/tokenplace-relay` images from the token.place
  repository's CI, including immutable deploy tags such as
  `main-REPLACE_SHORTSHA`.
- App repository responsibility: package and publish the Helm chart at
  `oci://ghcr.io/futuroptimist/charts/tokenplace` with immutable chart versions.
- Sugarkube responsibility: select kubeconfig/environment, read
  `docs/examples/apps/tokenplace.env`, pin the chart version from
  `docs/apps/tokenplace.version`, deploy the selected image tag with Helm, and
  run status/verify/log helpers.
- Cloudflare responsibility: DNS and tunnel routes for the public hostnames live
  outside Helm; the chart only creates Kubernetes resources behind Traefik.

| Coordinate | Value |
| --- | --- |
| App config | `docs/examples/apps/tokenplace.env` |
| Image | `ghcr.io/futuroptimist/tokenplace-relay` |
| Chart | `oci://ghcr.io/futuroptimist/charts/tokenplace` |
| Release | `tokenplace` |
| Namespace | `tokenplace` |
| Chart pin | `docs/apps/tokenplace.version` |
| Production tag pin | `docs/apps/tokenplace.prod.tag` |
| Verify paths | `/`, `/livez`, `/healthz`, `/relay/diagnostics` |

## 2. Environment topology

- `env=dev`: non-production defaults using
  `docs/examples/tokenplace.values.dev.yaml`.
- `env=staging`: staging host `staging.token.place`, values chain
  `docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.staging.yaml`.
- `env=prod`: production host `token.place`, values chain
  `docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.prod.yaml`.

## 3. Find or publish GHCR image

Find the latest successful token.place image workflow and copy the immutable tag
for the relay image.

```bash
APP_TAG=main-REPLACE_SHORTSHA # replace with the immutable GHCR image tag from token.place CI
```

```bash
gh run list --repo futuroptimist/token.place --workflow ci-image.yml --status success --limit 10
```

If no usable immutable tag exists, publish one from the token.place repository's
image workflow before deploying from Sugarkube.

```bash
gh workflow run ci-image.yml --repo futuroptimist/token.place --ref main
```

## 4. Confirm/publish OCI chart

Sugarkube reads the chart version from `docs/apps/tokenplace.version`. Confirm
that GHCR has that chart before deploying.

```bash
CHART_VERSION=$(grep -E '^[0-9]+\.[0-9]+\.[0-9]+' docs/apps/tokenplace.version | head -n1)
```

```bash
helm show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version "$CHART_VERSION"
```

If the chart changed in the token.place repository and GHCR does not have the
desired version yet, publish it from the chart workflow before updating the
Sugarkube chart pin.

```bash
gh workflow run ci-helm.yml --repo futuroptimist/token.place --ref main
```

## 5. Deploy staging

Preferred generic command:

```bash
APP_TAG=main-REPLACE_SHORTSHA # replace with the immutable GHCR image tag from token.place CI
just app-deploy app=tokenplace env=staging tag="$APP_TAG"
```

Current compatibility wrapper:

```bash
APP_TAG=main-REPLACE_SHORTSHA # replace with the immutable GHCR image tag from token.place CI
just tokenplace-oci-deploy env=staging tag="$APP_TAG"
```

## 6. Verify staging

```bash
just app-status app=tokenplace env=staging
```

```bash
just app-verify app=tokenplace env=staging
```

```bash
curl -fsS https://staging.token.place/livez
```

```bash
curl -fsS https://staging.token.place/healthz
```

```bash
curl -fsS https://staging.token.place/relay/diagnostics | jq .
```

## 7. Promote production

Promote only after staging sign-off. Record the approved immutable tag in your
release notes and, when appropriate, in `docs/apps/tokenplace.prod.tag`.

Preferred generic command:

```bash
APP_TAG=main-REPLACE_SHORTSHA # replace with the staging-approved immutable GHCR image tag
just app-promote-prod app=tokenplace tag="$APP_TAG"
```

Current compatibility wrapper:

```bash
APP_TAG=main-REPLACE_SHORTSHA # replace with the staging-approved immutable GHCR image tag
just tokenplace-oci-promote-prod tag="$APP_TAG"
```

If `docs/apps/tokenplace.prod.tag` already contains the approved production tag,
the generic promotion command can read it by omitting `tag=`.

```bash
just app-promote-prod app=tokenplace
```

## 8. Verify production

```bash
just app-status app=tokenplace env=prod
```

```bash
just app-verify app=tokenplace env=prod
```

```bash
curl -fsS https://token.place/livez
```

```bash
curl -fsS https://token.place/healthz
```

```bash
curl -fsS https://token.place/relay/diagnostics | jq .
```

## 9. Rollback

Rollback by immutable tag with the generic redeploy helper:

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA # replace with the previous known-good immutable GHCR image tag
just app-redeploy app=tokenplace env=prod tag="$APP_TAG"
```

Rollback staging the same way if the failure is caught before promotion:

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA # replace with the previous known-good immutable GHCR image tag
just app-redeploy app=tokenplace env=staging tag="$APP_TAG"
```

Rollback by Helm revision when a revision number is known:

```bash
TOKENPLACE_REVISION=12 # replace with the known-good Helm revision
just tokenplace-rollback release=tokenplace namespace=tokenplace revision="$TOKENPLACE_REVISION"
```

## 10. Troubleshooting

GHCR authentication and chart pull failures commonly show up as Helm `401` or
`403` errors. Log in to GHCR with a package-read credential, then retry the
chart check.

```bash
CHART_VERSION=$(grep -E '^[0-9]+\.[0-9]+\.[0-9]+' docs/apps/tokenplace.version | head -n1)
helm show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version "$CHART_VERSION"
```

Inspect status, logs, ingress, and tunnel routing:

```bash
just app-status app=tokenplace env=staging
```

```bash
just tokenplace-debug-logs-env env=staging
```

```bash
just cluster-status
```

```bash
just traefik-status
```

```bash
just cf-tunnel-debug
```

Cloudflare routes are external to Helm. Create or repair routes outside the
chart when DNS/tunnel routing is the failing layer.

```bash
just cf-tunnel-route host=staging.token.place
```

## 11. App-specific notes

- token.place deploys the canonical relay image. Do not deploy stale Docker-first
  images or duplicate relay variants for staging/prod.
- Preserve relay-blind behavior: logs, diagnostics, and app status must not expose
  plaintext message contents or secrets.
- The `/relay/diagnostics` endpoint is safe for smoke checks because it reports
  operational metadata, not decrypted relay payloads.
