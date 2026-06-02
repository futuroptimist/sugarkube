# k3s danielsmith.io runbook (prod)

Use this environment runbook for production `danielsmith.io` operations. The full
uniform app flow lives in [danielsmith.io on Sugarkube](apps/danielsmith.md); this
page keeps the production commands copy-pasteable.

## Responsibilities

- App repo: publish the approved static-site image and immutable OCI chart.
- Sugarkube: promote the staging-verified image tag to `env=prod`, verify, inspect
  logs, and roll back.
- Cloudflare: route `danielsmith.io` to Traefik outside Helm.

## Promote production

Preferred generic command:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just app-promote-prod app=danielsmith tag="$APP_TAG"
```

Compatibility wrapper:

```bash
just danielsmith-oci-promote-prod tag="$APP_TAG"
```

## Production verify

```bash
just app-status app=danielsmith env=prod
```

```bash
just app-verify app=danielsmith env=prod
```

Manual checks:

```bash
kubectl --context sugar-prod -n danielsmith rollout status deploy/danielsmith --timeout=180s
```

```bash
curl -fsS https://danielsmith.io/livez
```

```bash
curl -fsS https://danielsmith.io/healthz
```

```bash
curl -fsS https://danielsmith.io/
```

## Production rollback

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA
```

```bash
just app-promote-prod app=danielsmith tag="$APP_TAG"
```

Helm revision rollback, only with a confirmed revision:

```bash
APP_REVISION=12
```

```bash
just tokenplace-rollback release=danielsmith namespace=danielsmith revision="$APP_REVISION"
```

## Cloudflare route

```bash
just cf-tunnel-route host=danielsmith.io
```

## Troubleshooting

```bash
just app-config app=danielsmith env=prod
```

```bash
just app-status app=danielsmith env=prod
```

```bash
kubectl --context sugar-prod -n danielsmith logs deploy/danielsmith --tail=120
```
