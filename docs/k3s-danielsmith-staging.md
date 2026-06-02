# k3s danielsmith.io runbook (staging)

This environment-specific page is a quick staging checklist. Use the canonical
uniform app runbook for the complete GHCR-first flow:
[`docs/apps/danielsmith.md`](apps/danielsmith.md).

## Responsibilities

- App repo: publish the static-site image and Helm chart to GHCR.
- Sugarkube: select the staging kubeconfig, deploy the configured chart and tag,
  then run status/verify/log helpers.
- Cloudflare: route `staging.danielsmith.io` to the staging Traefik endpoint
  outside Helm.

## Deploy staging

Preferred generic command:

```bash
APP_TAG=main-REPLACE_SHORTSHA # replace with the immutable GHCR image tag from danielsmith.io CI
just app-deploy app=danielsmith env=staging tag="$APP_TAG"
```

Compatibility wrapper:

```bash
APP_TAG=main-REPLACE_SHORTSHA # replace with the immutable GHCR image tag from danielsmith.io CI
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
curl -fsS https://staging.danielsmith.io/
```

## Roll back staging

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA # replace with the previous known-good immutable GHCR image tag
just app-redeploy app=danielsmith env=staging tag="$APP_TAG"
```

## Troubleshooting

```bash
just danielsmith-debug-logs-env env=staging
```

```bash
just cf-tunnel-route host=staging.danielsmith.io
```
