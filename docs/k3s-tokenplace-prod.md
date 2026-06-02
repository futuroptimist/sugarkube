# k3s token.place runbook (prod)

Use this environment runbook for production token.place operations after staging sign-off. The full uniform GHCR-first flow lives in [docs/apps/tokenplace.md](apps/tokenplace.md); this page keeps the production commands copy-pasteable.

## Scope and ownership

- App repo: publishes `ghcr.io/futuroptimist/tokenplace-relay` and `oci://ghcr.io/futuroptimist/charts/tokenplace`.
- Sugarkube: selects `env=prod`, deploys the pinned chart with the approved immutable image tag, and verifies the release.
- Cloudflare: routes `token.place` to Traefik outside Helm.


### Required staging sign-off before promotion

Production promotion is blocked until staging proves the actual relay-compute path, not just web/TLS health. Confirm these staging artifacts before running the prod command:

- [ ] `app-status`, `app-verify`, `/healthz`, `/livez`, and `/relay/diagnostics` passed for staging.
- [ ] A real external desktop or compute node registered to `staging.token.place` and appeared in staging `/healthz` and `/relay/diagnostics`.
- [ ] A real E2EE request/response succeeded through that staging-registered compute node.
- [ ] The `token.place` Cloudflare route points at Traefik before prod cutover.

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

### Required production relay proof

Do not mark production healthy on generic checks alone. Capture separate production relay evidence after promotion:

- [ ] A real external desktop or compute node is configured for `token.place`, registers to production, and does not silently fall back to staging.
- [ ] The production-registered compute node appears in prod `/healthz` and `/relay/diagnostics`.
- [ ] A real E2EE request/response succeeds through the production-registered compute node.
- [ ] Post-test `/healthz`, `/relay/diagnostics`, and relay logs are captured after the E2EE test.

```bash
TOKENPLACE_HOST=token.place
kubectl -n tokenplace get deploy tokenplace -o yaml > /tmp/tokenplace-prod-deployment.yaml
# First run real prod compute-node registration and the prod E2EE
# request/response. Then capture post-test evidence:
curl -fsS "https://${TOKENPLACE_HOST}/healthz" | tee /tmp/tokenplace-prod-healthz.json
curl -fsS "https://${TOKENPLACE_HOST}/relay/diagnostics" | tee /tmp/tokenplace-prod-diagnostics.json
kubectl -n tokenplace logs deploy/tokenplace --since=30m --tail=500 \
  | tee /tmp/tokenplace-prod-relay-after-compute.log
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
