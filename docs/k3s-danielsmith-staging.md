# k3s danielsmith.io runbook (staging)

Use this environment runbook for staging-only danielsmith.io operations. The full uniform GHCR-first flow lives in [docs/apps/danielsmith.md](apps/danielsmith.md); this page keeps the environment-specific commands copy-pasteable.

## Scope and ownership

- App repo: publishes `ghcr.io/futuroptimist/danielsmith.io` and `oci://ghcr.io/futuroptimist/charts/danielsmith`.
- Sugarkube: selects `env=staging`, deploys the pinned chart with the selected immutable image tag, and verifies the release.
- Cloudflare: routes `staging.danielsmith.io` to Traefik outside Helm.

## Deploy staging

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

Preferred generic command:

```bash
just app-deploy app=danielsmith env=staging tag="$APP_TAG"
```

Compatibility shim while migration is in progress:

```bash
just danielsmith-oci-deploy env=staging tag="$APP_TAG"
```

## Verify staging

```bash
just app-status app=danielsmith env=staging
```

```bash
just app-verify app=danielsmith env=staging
```

```bash
curl -fsS https://staging.danielsmith.io/
```

## Rollback staging

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA
```

```bash
just app-redeploy app=danielsmith env=staging tag="$APP_TAG"
```

## Cloudflare route

Cloudflare Tunnel routing is external to Helm.

```bash
just cf-tunnel-route host=staging.danielsmith.io
```

## Troubleshooting

```bash
just app-config app=danielsmith env=staging
```

```bash
just danielsmith-debug-logs-env env=staging
```
