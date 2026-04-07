# k3s token.place runbook (staging)

Staging runbook for token.place on Sugarkube. Use this environment for release
validation before production promotion.

## Purpose

- Candidate validation with production-like routing and security controls.
- Rehearsal for rollback, secret rotation, and operator runbook execution.

## Suggested defaults

- Environment: `staging`
- Namespace: `tokenplace` (configurable)
- Release: `tokenplace` (configurable)
- Hostname: `staging.token.place`

## Prerequisites

- `just kubeconfig-env env=staging`
- Immutable image tag available for candidate release
- Staging values overlays published
- Cloudflare tunnel + DNS + TLS cert flow confirmed

## Deploy / upgrade / rollback

```bash
TOKENPLACE_CHART='<chart-ref>' \
TOKENPLACE_VALUES_STAGING='path/base.yaml,path/staging.yaml' \
just tokenplace-install env=staging tag=<immutable-tag>

just tokenplace-upgrade env=staging tag=<immutable-tag>

just tokenplace-rollback env=staging revision=<helm-revision>
```

## Validation checks

```bash
just tokenplace-status env=staging
TOKENPLACE_VALIDATE_URL='https://staging.token.place' just tokenplace-validate env=staging
just tokenplace-logs namespace=tokenplace
```

Recommended additional checks:

- `helm -n <namespace> history <release>` before and after deploy
- `kubectl -n <namespace> get ingress,svc,pods`
- Relay-to-compute smoke test for API v1 auth and latency expectations

## Cloudflare / ingress expectations

- Cloudflare tunnel routes `staging.token.place` to Traefik service.
- Ingress annotations for cert-manager are present.
- TLS secret exists and refreshes automatically.

## Notes

- Staging should mirror prod topology as closely as practical.
- Use immutable tags for reproducible incident response.
