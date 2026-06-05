# k3s danielsmith.io runbook (prod)

Use this environment runbook for production danielsmith.io operations after staging sign-off. The full uniform GHCR-first flow lives in [docs/apps/danielsmith.md](apps/danielsmith.md); this page keeps the production commands copy-pasteable.

## Scope and ownership

- App repo: publishes `ghcr.io/futuroptimist/danielsmith.io` and `oci://ghcr.io/futuroptimist/charts/danielsmith`.
- Sugarkube: selects `env=prod`, deploys the pinned chart with the approved immutable image tag, and verifies the release.
- Cloudflare: routes `danielsmith.io` to Traefik outside Helm.

## Promote production

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

Preferred generic command:

```bash
just app-promote-prod app=danielsmith tag="$APP_TAG"
```

Compatibility shim while migration is in progress:

```bash
just danielsmith-oci-promote-prod tag="$APP_TAG"
```

## Verify production

```bash
just app-status app=danielsmith env=prod
```

```bash
just app-verify app=danielsmith env=prod
```

```bash
curl -fsS https://danielsmith.io/
```

Verify the sidecar-backed public GitHub metrics cache. The sidecar uses unauthenticated public GitHub API requests, so no GitHub token or Secret is needed for the current public stars flow.

```bash
curl -fsS https://danielsmith.io/runtime/github-metrics.json
```

```bash
curl -fsS https://danielsmith.io/runtime/github-metrics.json \
  | jq -e '.schemaVersion and .generatedAt and (.repos | type == "object")'
```

```bash
kubectl --context sugar-prod -n danielsmith logs deploy/danielsmith -c github-metrics-cache --tail=100
```

## Rollback production

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA
```

```bash
just app-redeploy app=danielsmith env=prod tag="$APP_TAG"
```

## Cloudflare route

Cloudflare Tunnel routing is external to Helm.

```bash
just cf-tunnel-route host=danielsmith.io
```

## Troubleshooting

```bash
just app-config app=danielsmith env=prod
```

```bash
just danielsmith-debug-logs-env env=prod
```

If `/runtime/github-metrics.json` is missing or stale, check the `github-metrics-cache` sidecar logs before changing values. Hourly refresh means star counts can be about an hour old; GitHub rate limits should be handled by serving the existing cache through the TTL/grace window rather than by adding a token.
