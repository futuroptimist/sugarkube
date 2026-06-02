# k3s token.place runbook (staging)

This environment-specific page is a thin staging checklist. Use the canonical generic flow in
[`docs/apps/tokenplace.md`](apps/tokenplace.md) for the full artifact model, chart checks,
verification, rollback, and troubleshooting details.

## Staging deploy

Preferred generic deploy:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just app-deploy app=tokenplace env=staging tag="$APP_TAG"
```

Compatibility shim while generic app recipes are exercised across routine releases:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just tokenplace-oci-deploy env=staging tag="$APP_TAG"
```

## Staging verify

```bash
just app-verify app=tokenplace env=staging
```

```bash
just app-status app=tokenplace env=staging
```

```bash
curl -fsS https://staging.token.place/relay/diagnostics | jq .
```

## Staging rollback

```bash
PREVIOUS_TAG=main-REPLACE_PREVIOUS_SHORTSHA
```

```bash
just app-deploy app=tokenplace env=staging tag="$PREVIOUS_TAG"
```

```bash
HELM_REVISION=12
```

```bash
just tokenplace-rollback release=tokenplace namespace=tokenplace revision="$HELM_REVISION"
```

## Cloudflare route

Cloudflare Tunnel routing is outside Helm. Route staging traffic to Traefik before expecting public
HTTPS checks to pass.

```bash
just cf-tunnel-route host=staging.token.place
```
