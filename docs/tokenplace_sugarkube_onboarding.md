# token.place Sugarkube onboarding

This guide prepares Sugarkube to host `token.place` as a first-class application after
`token.place` completes the API v1 convergence and runtime migration work.

Use this as the control document for onboarding scope, release contracts, and ownership.

## Why token.place belongs on Sugarkube

- Sugarkube already provides a repeatable k3s + Traefik + Cloudflare Tunnel operating model.
- token.place needs reliable relay/API ingress and operational runbooks that match dspace patterns.
- Sugarkube can host the control-plane-facing token.place services while external compute nodes
  continue to execute GPU/CPU-heavy workloads.

## Required token.place readiness before onboarding

Before production onboarding, token.place should provide:

1. Stable API v1 behavior across desktop/server/relay clients.
2. A published deployment artifact contract (chart reference, values schema, image tags).
3. Environment-specific config and secrets model suitable for `dev`, `staging`, and `prod`.
4. Health/readiness endpoints and logs that support day-two operations.
5. Rollback-safe releases (immutable image tags and documented Helm revision practices).

## Release artifact expectations

The onboarding contract should define all of the following explicitly:

- **Chart reference:** OCI chart or in-repo chart path.
- **Release name(s):** Helm release identifier per environment.
- **Namespace(s):** dedicated Kubernetes namespace(s) for token.place components.
- **Values layering:** base + environment overlays.
- **Image policy:** immutable tags for promotion/rollback, optional mutable tags for dev only.

If any item is still in flight, keep using parameterized Just recipes instead of hardcoded values.

## Namespace/release/chart/value-file model (standardized vs configurable)

Standardized in Sugarkube:

- Environment names: `dev`, `staging`, `prod`.
- Workflow verbs: status, deploy, upgrade, rollback, logs, validate, port-forward.
- Operator command surface via `just tokenplace-*` recipes.

Configurable per token.place onboarding cut:

- `release=<name>`
- `namespace=<name>`
- `chart=<chart-ref-or-path>`
- `values=<comma-separated-values-files>`
- `selector=<label-selector>`

## Environment mapping

- **dev:** low-risk integration and quick feedback.
- **staging:** production-like validation and sign-off.
- **prod:** externally visible release with strict rollout/rollback controls.

See environment runbooks:

- [docs/k3s-tokenplace-dev.md](k3s-tokenplace-dev.md)
- [docs/k3s-tokenplace-staging.md](k3s-tokenplace-staging.md)
- [docs/k3s-tokenplace-prod.md](k3s-tokenplace-prod.md)

## Operational ownership boundaries

- **token.place team owns:** app/chart behavior, image publishing, API contracts, app-level SLOs.
- **Sugarkube operators own:** cluster runtime, ingress/tunnel posture, secret injection path,
  deployment execution, and incident triage on the cluster side.

## Operator workflow (Just recipes)

Use these recipes as the stable operator interface:

- `just tokenplace-status ...`
- `just tokenplace-deploy ...`
- `just tokenplace-upgrade ...`
- `just tokenplace-rollback revision=<n> ...`
- `just tokenplace-logs ...`
- `just tokenplace-validate ...`
- `just tokenplace-port-forward ...`

For the existing relay-only deployment, keep using:

- `just tokenplace-relay-oci-redeploy ...`
- `just tokenplace-relay-status`
- `just tokenplace-relay-logs`
- `just tokenplace-relay-port-forward`

## App catalog links

- [apps/tokenplace.md](apps/tokenplace.md)
- [apps/tokenplace-relay.md](apps/tokenplace-relay.md)
