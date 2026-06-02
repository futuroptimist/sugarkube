# k3s token.place runbook (production)

This environment-specific page is a thin production checklist. Use the canonical generic flow in
[`docs/apps/tokenplace.md`](apps/tokenplace.md) for the full artifact model, chart checks,
verification, rollback, and troubleshooting details.

## Production promotion

Promote only the immutable tag that passed staging.

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just app-promote-prod app=tokenplace tag="$APP_TAG"
```

Compatibility shim while generic app recipes are exercised across routine releases:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just tokenplace-oci-promote-prod tag="$APP_TAG"
```

## Production verify

```bash
just app-verify app=tokenplace env=prod
```

```bash
just app-status app=tokenplace env=prod
```

```bash
curl -fsS https://token.place/relay/diagnostics | jq .
```

## Production rollback

```bash
PREVIOUS_TAG=main-REPLACE_PREVIOUS_SHORTSHA
```

```bash
just app-deploy app=tokenplace env=prod tag="$PREVIOUS_TAG"
```

```bash
HELM_REVISION=12
```

```bash
just tokenplace-rollback release=tokenplace namespace=tokenplace revision="$HELM_REVISION"
```

## Cloudflare route

Cloudflare Tunnel routing is outside Helm. Route production traffic to Traefik before expecting
public HTTPS checks to pass.

```bash
just cf-tunnel-route host=token.place
```
