# k3s token.place runbook (staging)

Use this environment runbook for staging-only token.place operations. The full uniform GHCR-first flow lives in [docs/apps/tokenplace.md](apps/tokenplace.md); this page keeps the environment-specific commands copy-pasteable.

## Scope and ownership

- App repo: publishes `ghcr.io/futuroptimist/tokenplace-relay` and `oci://ghcr.io/futuroptimist/charts/tokenplace`.
- Sugarkube: selects `env=staging`, deploys the pinned chart with the selected immutable image tag, and verifies the release.
- Cloudflare: routes `staging.token.place` to Traefik outside Helm.

## Deploy staging

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

Preferred generic command:

```bash
just app-deploy app=tokenplace env=staging tag="$APP_TAG"
```

Compatibility shim while migration is in progress:

```bash
just tokenplace-oci-deploy env=staging tag="$APP_TAG"
```

## Verify staging

```bash
just app-status app=tokenplace env=staging
```

```bash
just app-verify app=tokenplace env=staging
```

```bash
curl -fsS https://staging.token.place/relay/diagnostics | jq .
```

### Relay-compute sign-off gate

Generic HTTP checks are necessary but do not prove token.place's relay workflow. Do not sign off staging for production promotion until all relay-compute checks pass:

- [ ] Synthetic API v1 compute-node registration succeeds against `https://staging.token.place/api/v1/relay/servers/register`.
- [ ] Synthetic API v1 compute-node polling succeeds against `https://staging.token.place/api/v1/relay/servers/poll` without a client-side timeout.
- [ ] A real desktop or compute node points at `staging.token.place`, registers to staging, and appears in `/healthz` and `/relay/diagnostics`.
- [ ] A real E2EE request/response succeeds through the staging relay.

Use the full synthetic register/poll block in [the canonical token.place runbook](apps/tokenplace.md#staging-relay-compute-sign-off), then complete the real desktop or compute-node E2EE test before promotion.

## Rollback staging

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA
```

```bash
just app-redeploy app=tokenplace env=staging tag="$APP_TAG"
```

## Cloudflare route

Cloudflare Tunnel routing is external to Helm.

```bash
just cf-tunnel-route host=staging.token.place
```

## Troubleshooting

```bash
just app-config app=tokenplace env=staging
```

```bash
just tokenplace-debug-logs-env env=staging
```
