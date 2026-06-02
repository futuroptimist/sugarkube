# k3s token.place runbook (prod)

This environment-specific page is a quick production checklist. Use the canonical
uniform app runbook for the complete GHCR-first flow:
[`docs/apps/tokenplace.md`](apps/tokenplace.md).

## Responsibilities

- App repo: publish the relay image and Helm chart to GHCR.
- Sugarkube: select the production kubeconfig, deploy the configured chart and
  approved tag, then run status/verify/log helpers.
- Cloudflare: route `token.place` to the production Traefik endpoint outside
  Helm.

## Promote production

Preferred generic command:

```bash
APP_TAG=main-REPLACE_SHORTSHA # replace with the staging-approved immutable GHCR image tag
just app-promote-prod app=tokenplace tag="$APP_TAG"
```

Compatibility wrapper:

```bash
APP_TAG=main-REPLACE_SHORTSHA # replace with the staging-approved immutable GHCR image tag
just tokenplace-oci-promote-prod tag="$APP_TAG"
```

If `docs/apps/tokenplace.prod.tag` already contains the approved tag:

```bash
just app-promote-prod app=tokenplace
```

## Verify production

```bash
just app-status app=tokenplace env=prod
```

```bash
just app-verify app=tokenplace env=prod
```

```bash
curl -fsS https://token.place/relay/diagnostics | jq .
```

## Roll back production

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA # replace with the previous known-good immutable GHCR image tag
just app-redeploy app=tokenplace env=prod tag="$APP_TAG"
```

## Troubleshooting

```bash
just tokenplace-debug-logs-env env=prod
```

```bash
just cf-tunnel-route host=token.place
```
