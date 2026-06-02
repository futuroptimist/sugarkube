# k3s danielsmith.io runbook (prod)

This environment-specific page is a quick production checklist. Use the
canonical uniform app runbook for the complete GHCR-first flow:
[`docs/apps/danielsmith.md`](apps/danielsmith.md).

## Responsibilities

- App repo: publish the static-site image and Helm chart to GHCR.
- Sugarkube: select the production kubeconfig, deploy the configured chart and
  approved tag, then run status/verify/log helpers.
- Cloudflare: route `danielsmith.io` to the production Traefik endpoint outside
  Helm.

## Promote production

Preferred generic command:

```bash
APP_TAG=main-REPLACE_SHORTSHA # replace with the staging-approved immutable GHCR image tag
just app-promote-prod app=danielsmith tag="$APP_TAG"
```

Compatibility wrapper:

```bash
APP_TAG=main-REPLACE_SHORTSHA # replace with the staging-approved immutable GHCR image tag
just danielsmith-oci-promote-prod tag="$APP_TAG"
```

If `docs/apps/danielsmith.prod.tag` already contains the approved tag:

```bash
just app-promote-prod app=danielsmith
```

## Verify production

```bash
just app-status app=danielsmith env=prod
```

```bash
just app-verify app=danielsmith env=prod
```

```bash
curl -fsS https://danielsmith.io/
```

## Roll back production

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA # replace with the previous known-good immutable GHCR image tag
just app-redeploy app=danielsmith env=prod tag="$APP_TAG"
```

## Troubleshooting

```bash
just danielsmith-debug-logs-env env=prod
```

```bash
just cf-tunnel-route host=danielsmith.io
```
