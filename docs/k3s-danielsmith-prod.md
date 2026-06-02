# k3s danielsmith.io runbook (production)

This environment-specific page is a thin production checklist. Use the canonical generic flow in
[`docs/apps/danielsmith.md`](apps/danielsmith.md) for the full artifact model, chart checks,
verification, rollback, and troubleshooting details.

## Production promotion

Promote only the immutable tag that passed staging.

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just app-promote-prod app=danielsmith tag="$APP_TAG"
```

Compatibility shim while generic app recipes are exercised across routine releases:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just danielsmith-oci-promote-prod tag="$APP_TAG"
```

## Production verify

```bash
just app-verify app=danielsmith env=prod
```

```bash
just app-status app=danielsmith env=prod
```

```bash
curl -fsS https://danielsmith.io/healthz
```

## Production rollback

```bash
PREVIOUS_TAG=main-REPLACE_PREVIOUS_SHORTSHA
```

```bash
just app-deploy app=danielsmith env=prod tag="$PREVIOUS_TAG"
```

```bash
HELM_REVISION=12
```

```bash
just tokenplace-rollback release=danielsmith namespace=danielsmith revision="$HELM_REVISION"
```

## Cloudflare route

Cloudflare Tunnel routing is outside Helm. Route production traffic to Traefik before expecting
public HTTPS checks to pass.

```bash
just cf-tunnel-route host=danielsmith.io
```
