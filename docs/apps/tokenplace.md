# token.place on Sugarkube

Use this runbook for GHCR-first token.place deploys from published GitHub Actions artifacts to
Sugarkube. The generic app recipes are the preferred future path; the `tokenplace-*` recipes are
compatibility shims that stay documented until the generic flow has been exercised across routine
releases.

## 1. Artifact model

App repo responsibilities:

- Build and publish the canonical relay image to GHCR.
- Build and publish the token.place Helm chart as an immutable OCI artifact.
- Preserve relay-blind E2EE behavior; relay diagnostics must expose safe routing metadata only.

Sugarkube responsibilities:

- Select kubeconfig and environment.
- Read `docs/examples/apps/tokenplace.env` or a copied local `apps/tokenplace.env`.
- Run Helm deploys with the configured values overlays and chart version pin.
- Verify Kubernetes status, public HTTPS paths, and logs.

Cloudflare responsibilities:

- DNS and Cloudflare Tunnel routes are configured outside Helm.
- Route `staging.token.place` and `token.place` to Traefik before public HTTPS checks can pass.

Current artifact contract:

| Field | Value |
| --- | --- |
| Image | `ghcr.io/futuroptimist/tokenplace-relay` |
| Chart | `oci://ghcr.io/futuroptimist/charts/tokenplace` |
| Release | `tokenplace` |
| Namespace | `tokenplace` |
| App config | `docs/examples/apps/tokenplace.env` |
| Chart version pin | `docs/apps/tokenplace.version` |
| Production tag pin | `docs/apps/tokenplace.prod.tag` |
| Verify paths | `/`, `/livez`, `/healthz`, `/relay/diagnostics` |

## 2. Environment topology

Values overlays decide routing; image tags decide the relay build.

| Environment | Sugarkube values chain | Public host |
| --- | --- | --- |
| `dev` | `docs/examples/tokenplace.values.dev.yaml` | Local/dev only unless overridden |
| `staging` | `docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.staging.yaml` | `staging.token.place` |
| `prod` | `docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.prod.yaml` | `token.place` |

Cloudflare Tunnel routing is external to Helm. One environment tunnel can serve multiple app
hostnames by routing all of them to Traefik and letting Kubernetes Ingress match on `Host`.

## 3. Find or publish GHCR image

Find the successful image workflow run in the token.place app repo, then copy its immutable relay
image tag. Prefer branch-SHA tags such as `main-REPLACE_SHORTSHA` or semver release tags. Do not
deploy mutable tags such as `latest`, `main`, `staging`, or `prod` through the generic recipes.

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

Validate the tag shape locally before deploying:

```bash
python3 scripts/app_config.py validate-tag "$APP_TAG"
```

If no immutable image exists yet, publish one from the app repo's image workflow, then return here
with the resulting GHCR tag. Local `docker build` commands are for app-repo development only, not
Sugarkube staging or production deploys.

## 4. Confirm/publish OCI chart

Confirm Sugarkube can read the pinned chart version:

```bash
CHART_VERSION=$(sed -e 's/#.*$//' -e '/^[[:space:]]*$/d' docs/apps/tokenplace.version | head -n1)
```

```bash
helm show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version "$CHART_VERSION"
```

If the chart changed in the token.place app repo, publish a new immutable OCI chart there first and
then update `docs/apps/tokenplace.version` in Sugarkube. If only the image changed, keep the chart
version pin unchanged.

## 5. Deploy staging

Preferred generic deploy:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just app-deploy app=tokenplace env=staging tag="$APP_TAG"
```

Compatibility wrapper while the generic flow bakes in:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just tokenplace-oci-deploy env=staging tag="$APP_TAG"
```

## 6. Verify staging

Generic HTTPS smoke checks from the app config:

```bash
just app-verify app=tokenplace env=staging
```

Kubernetes status with the generic app config:

```bash
just app-status app=tokenplace env=staging
```

Compatibility status/log helpers:

```bash
just tokenplace-status
```

```bash
just tokenplace-debug-logs-env env=staging
```

Manual public checks when you need the exact commands:

```bash
curl -fsS https://staging.token.place/
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

Promote only the exact immutable tag that passed staging.

Preferred generic production promotion:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just app-promote-prod app=tokenplace tag="$APP_TAG"
```

Compatibility wrapper:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just tokenplace-oci-promote-prod tag="$APP_TAG"
```

If `docs/apps/tokenplace.prod.tag` has already been reviewed and pinned to the approved tag, both
production promotion recipes can read it when `tag=` is omitted. Passing `tag=` is still clearer for
copy-pasteable release notes.

## 8. Verify production

Generic HTTPS smoke checks:

```bash
just app-verify app=tokenplace env=prod
```

Generic status:

```bash
just app-status app=tokenplace env=prod
```

Manual public checks:

```bash
curl -fsS https://token.place/
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

Prefer immutable-tag rollback when the bad release maps to a single image tag:

```bash
PREVIOUS_TAG=main-REPLACE_PREVIOUS_SHORTSHA
```

```bash
just app-deploy app=tokenplace env=prod tag="$PREVIOUS_TAG"
```

Use Helm revision rollback when you must restore the full rendered release state:

```bash
HELM_REVISION=12
```

```bash
just tokenplace-rollback release=tokenplace namespace=tokenplace revision="$HELM_REVISION"
```

## 10. Troubleshooting

GHCR auth failures usually look like `401`, `403`, or `denied`. Log in and retry the chart check:

```bash
helm registry login ghcr.io -u "$GHCR_USER"
```

```bash
helm show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version "$CHART_VERSION"
```

Check rendered app config before deploying:

```bash
just app-config app=tokenplace env=staging
```

Inspect cluster state and ingress routing:

```bash
just cluster-status
```

```bash
just traefik-status
```

```bash
just cf-tunnel-debug
```

Create or refresh Cloudflare Tunnel routes outside Helm when DNS is the blocker:

```bash
just cf-tunnel-route host=staging.token.place
```

```bash
just cf-tunnel-route host=token.place
```

## 11. App-specific notes

- token.place currently deploys the canonical relay image through the tokenplace chart.
- Relay state, logs, and diagnostics must remain ciphertext-only plus safe routing metadata.
- App-specific API v1 and relay smoke checks belong in the token.place app repo when they require
  app fixtures; Sugarkube keeps generic HTTPS checks plus `/relay/diagnostics`.
- The relay-focused legacy guide remains at `docs/apps/tokenplace-relay.md` for historical context,
  but this page is the primary generic deployment runbook.
