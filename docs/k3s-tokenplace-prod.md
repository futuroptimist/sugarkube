# k3s token.place runbook (prod)

Use this environment runbook for production token.place operations. The full
uniform app flow lives in [token.place on Sugarkube](apps/tokenplace.md); this
page keeps the production commands copy-pasteable.

## Responsibilities

- App repo: publish the approved relay image and immutable OCI chart.
- Sugarkube: promote the staging-verified image tag to `env=prod`, verify, inspect
  logs, and roll back.
- Cloudflare: route `token.place` to Traefik outside Helm.

## Promote production

Preferred generic command:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just app-promote-prod app=tokenplace tag="$APP_TAG"
```

Compatibility wrapper:

```bash
just tokenplace-oci-promote-prod tag="$APP_TAG"
```

## Production verify

```bash
just app-status app=tokenplace env=prod
```

```bash
just app-verify app=tokenplace env=prod
```

Manual checks:

```bash
kubectl --context sugar-prod -n tokenplace rollout status deploy/tokenplace --timeout=180s
```

```bash
curl -fsS https://token.place/livez
```

```bash
curl -fsS https://token.place/healthz
```

```bash
curl -fsS https://token.place/relay/diagnostics
```

```bash
curl -fsS https://token.place/
```

## Production rollback

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA
```

```bash
just app-promote-prod app=tokenplace tag="$APP_TAG"
```

Helm revision rollback, only with a confirmed revision:

```bash
APP_REVISION=12
```

```bash
just tokenplace-rollback release=tokenplace namespace=tokenplace revision="$APP_REVISION"
```

## Cloudflare route

```bash
just cf-tunnel-route host=token.place
```

## Troubleshooting

```bash
just app-config app=tokenplace env=prod
```

```bash
just app-status app=tokenplace env=prod
```

```bash
kubectl --context sugar-prod -n tokenplace logs deploy/tokenplace --tail=120
```
