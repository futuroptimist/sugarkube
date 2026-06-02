# k3s token.place runbook (staging)

Use this environment runbook for staging-only token.place operations. The full
uniform app flow lives in [token.place on Sugarkube](apps/tokenplace.md); this
page keeps the staging commands copy-pasteable.

## Responsibilities

- App repo: publish `ghcr.io/futuroptimist/tokenplace-relay:main-REPLACE_SHORTSHA`
  and `oci://ghcr.io/futuroptimist/charts/tokenplace`.
- Sugarkube: deploy `env=staging`, verify, inspect logs, and roll back.
- Cloudflare: route `staging.token.place` to Traefik outside Helm.

## Staging deploy

Preferred generic command:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just app-deploy app=tokenplace env=staging tag="$APP_TAG"
```

Compatibility wrapper:

```bash
just tokenplace-oci-deploy env=staging tag="$APP_TAG"
```

## Staging verify

```bash
just app-status app=tokenplace env=staging
```

```bash
just app-verify app=tokenplace env=staging
```

Manual checks:

```bash
kubectl --context sugar-staging -n tokenplace rollout status deploy/tokenplace --timeout=180s
```

```bash
curl -fsS https://staging.token.place/livez
```

```bash
curl -fsS https://staging.token.place/healthz
```

```bash
curl -fsS https://staging.token.place/relay/diagnostics
```

```bash
curl -fsS https://staging.token.place/
```

## Staging relay sign-off

Web/TLS checks are not enough for token.place. Before production promotion, also
confirm synthetic API v1 register/poll, an external compute-node registration,
and an E2EE request/response through that compute node. Avoid long-running public
`/healthz` watches until relay health and heartbeat routes are confirmed exempt
from public API rate limits.

## Staging rollback

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA
```

```bash
just app-deploy app=tokenplace env=staging tag="$APP_TAG"
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
just cf-tunnel-route host=staging.token.place
```

## Troubleshooting

```bash
just app-config app=tokenplace env=staging
```

```bash
just app-status app=tokenplace env=staging
```

```bash
kubectl --context sugar-staging -n tokenplace logs deploy/tokenplace --tail=120
```
