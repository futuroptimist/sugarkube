# k3s danielsmith.io runbook (staging)

Use this environment runbook for staging-only `danielsmith.io` operations. The
full uniform app flow lives in [danielsmith.io on Sugarkube](apps/danielsmith.md);
this page keeps the staging commands copy-pasteable.

## Responsibilities

- App repo: publish `ghcr.io/futuroptimist/danielsmith.io:main-REPLACE_SHORTSHA`
  and `oci://ghcr.io/futuroptimist/charts/danielsmith`.
- Sugarkube: deploy `env=staging`, verify, inspect logs, and roll back.
- Cloudflare: route `staging.danielsmith.io` to Traefik outside Helm.

## Staging deploy

Preferred generic command:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just app-deploy app=danielsmith env=staging tag="$APP_TAG"
```

Compatibility wrapper:

```bash
just danielsmith-oci-deploy env=staging tag="$APP_TAG"
```

## Staging verify

```bash
just app-status app=danielsmith env=staging
```

```bash
just app-verify app=danielsmith env=staging
```

Manual checks:

```bash
kubectl --context sugar-staging -n danielsmith rollout status deploy/danielsmith --timeout=180s
```

```bash
curl -fsS https://staging.danielsmith.io/livez
```

```bash
curl -fsS https://staging.danielsmith.io/healthz
```

```bash
curl -fsS https://staging.danielsmith.io/
```

## Staging rollback

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA
```

```bash
just app-deploy app=danielsmith env=staging tag="$APP_TAG"
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
just cf-tunnel-route host=staging.danielsmith.io
```

## Troubleshooting

```bash
just app-config app=danielsmith env=staging
```

```bash
just app-status app=danielsmith env=staging
```

```bash
kubectl --context sugar-staging -n danielsmith logs deploy/danielsmith --tail=120
```
