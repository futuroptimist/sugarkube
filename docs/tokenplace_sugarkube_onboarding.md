# token.place onboarding on Sugarkube

This document prepares Sugarkube for **first-class token.place operations** after
`token.place` completed API v1 convergence and relay hardening. It intentionally
focuses on onboarding contracts and operator workflow, not app implementation details.

## Why token.place belongs on Sugarkube

- Sugarkube already runs HA k3s, ingress, cert-manager, and Cloudflare tunnel routing.
- The platform has established Helm/Just operational conventions used for dspace and
  tokenplace-relay.
- token.place benefits from the same environment split (dev/staging/prod), release
  promotion flow, and operational runbooks.

## Preconditions before onboarding

token.place should be considered onboarding-ready when all are true:

1. API v1 is the canonical interface for relay + compute node traffic.
2. Relay behavior is production-grade (timeouts, retries, auth, telemetry).
3. Build/release artifacts are reproducible and environment-agnostic.
4. Secrets inventory exists with owners, rotation policy, and bootstrap path.
5. Rollback has been rehearsed in staging with immutable artifacts.

## Release artifact expectations

Sugarkube intentionally does **not** hard-code the final token.place chart/release
wiring yet. Instead, operators should provide:

- Helm chart reference (`TOKENPLACE_CHART`) — local path or OCI chart URL.
- Image tags (`tag=` or `TOKENPLACE_DEFAULT_TAG`) — immutable for promotions.
- Environment values files (`TOKENPLACE_VALUES_DEV|STAGING|PROD`) layered over
  shared defaults.

## Naming and environment mapping contract

Standardized in Sugarkube:

- Environment names: `dev`, `staging`, `prod`
- Task entry points: `just tokenplace-install|upgrade|rollback|status|validate`
- App-level documentation: `docs/apps/tokenplace.md`

Configurable per onboarding:

- Namespace (`TOKENPLACE_NAMESPACE`, default `tokenplace`)
- Release (`TOKENPLACE_RELEASE`, default `tokenplace`)
- Chart ref (`TOKENPLACE_CHART`, required)
- Service name used for port-forward (`TOKENPLACE_SERVICE`)

## Operational ownership boundaries

- **token.place app team:** chart contents, image publishing, app config schema,
  app-level SLOs, compute-node runtime behavior.
- **Sugarkube platform operators:** cluster health, ingress/TLS, namespace policy,
  release execution, rollback execution, and observability plumbing.
- **Shared responsibility:** secret lifecycle, incident response, and release
  sign-off gates.

## Environment runbooks

- [docs/k3s-tokenplace-dev.md](k3s-tokenplace-dev.md)
- [docs/k3s-tokenplace-staging.md](k3s-tokenplace-staging.md)
- [docs/k3s-tokenplace-prod.md](k3s-tokenplace-prod.md)
- [docs/apps/tokenplace.md](apps/tokenplace.md)

## Operator quickstart

```bash
# 1) Inspect status in staging (with env-aware kubeconfig)
just tokenplace-status env=staging

# 2) First install once chart wiring is finalized
TOKENPLACE_CHART='<oci-or-local-chart>' \
TOKENPLACE_VALUES_STAGING='path/to/base.yaml,path/to/staging.yaml' \
just tokenplace-install env=staging tag=<immutable-tag>

# 3) Routine upgrade
just tokenplace-upgrade env=staging tag=<new-immutable-tag>

# 4) Validate + optional external health URL
TOKENPLACE_VALIDATE_URL='https://staging.token.place' \
just tokenplace-validate env=staging
```

## Notes

- Keep production deployment pinned to immutable tags.
- Avoid embedding credentials in values files committed to this repository.
- Keep relay + compute-node trust boundaries explicit; see app runbook for topology.
