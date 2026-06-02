# k3s token.place runbook (prod)

Use this environment runbook for production token.place operations after staging sign-off. The full uniform GHCR-first flow lives in [docs/apps/tokenplace.md](apps/tokenplace.md); this page keeps the production commands copy-pasteable.

## Scope and ownership

- App repo: publishes `ghcr.io/futuroptimist/tokenplace-relay` and `oci://ghcr.io/futuroptimist/charts/tokenplace`.
- Sugarkube: selects `env=prod`, deploys the pinned chart with the approved immutable image tag, and verifies the release.
- Cloudflare: routes `token.place` to Traefik outside Helm.

## Promote production

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

Preferred generic command:

```bash
just app-promote-prod app=tokenplace tag="$APP_TAG"
```

Compatibility shim while migration is in progress:

```bash
just tokenplace-oci-promote-prod tag="$APP_TAG"
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

## Rollback production

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA
```

```bash
just app-redeploy app=tokenplace env=prod tag="$APP_TAG"
```

## Cloudflare route

Cloudflare Tunnel routing is external to Helm.

```bash
just cf-tunnel-route host=token.place
```

## Troubleshooting

```bash
just app-config app=tokenplace env=prod
```

```bash
just tokenplace-debug-logs-env env=prod
```
