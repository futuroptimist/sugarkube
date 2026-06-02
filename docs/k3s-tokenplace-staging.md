# k3s token.place runbook (staging)

This environment-specific page is a quick staging checklist. Use the canonical
uniform app runbook for the complete GHCR-first flow:
[`docs/apps/tokenplace.md`](apps/tokenplace.md).

## Responsibilities

- App repo: publish the relay image and Helm chart to GHCR.
- Sugarkube: select the staging kubeconfig, deploy the configured chart and tag,
  then run status/verify/log helpers.
- Cloudflare: route `staging.token.place` to the staging Traefik endpoint outside
  Helm.

## Deploy staging

Preferred generic command:

```bash
APP_TAG=main-REPLACE_SHORTSHA # replace with the immutable GHCR image tag from token.place CI
just app-deploy app=tokenplace env=staging tag="$APP_TAG"
```

Compatibility wrapper:

```bash
APP_TAG=main-REPLACE_SHORTSHA # replace with the immutable GHCR image tag from token.place CI
just tokenplace-oci-deploy env=staging tag="$APP_TAG"
```

## Verify staging

```bash
just app-status app=tokenplace env=staging
```

```bash
just app-verify app=tokenplace env=staging
```

```bash
curl -fsS https://staging.token.place/relay/diagnostics | jq .
```

## Roll back staging

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA # replace with the previous known-good immutable GHCR image tag
just app-redeploy app=tokenplace env=staging tag="$APP_TAG"
```

## Troubleshooting

```bash
just tokenplace-debug-logs-env env=staging
```

```bash
just cf-tunnel-route host=staging.token.place
```
