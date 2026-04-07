---
personas:
  - software
---

# token.place Sugarkube onboarding

This guide prepares Sugarkube operators to onboard **token.place** as a first-class
k3s workload once token.place release artifacts, chart packaging, and API v1 hardening
are complete.

For environment runbooks, see:

- [k3s-tokenplace-dev.md](k3s-tokenplace-dev.md)
- [k3s-tokenplace-staging.md](k3s-tokenplace-staging.md)
- [k3s-tokenplace-prod.md](k3s-tokenplace-prod.md)
- [apps/tokenplace.md](apps/tokenplace.md)

## Why token.place belongs on Sugarkube

- Sugarkube already provides repeatable k3s environment lanes (`dev`, `staging`, `prod`).
- Existing Traefik + Cloudflare Tunnel patterns map directly to token.place ingress needs.
- Existing `just`/Helm workflows match immutable-tag promotion and rollback operations.
- Keeping token.place ingress and relay control-plane services on Sugarkube allows compute
  workers to stay external and independently scalable.

## Readiness gates before onboarding

Do not perform production onboarding until token.place has all of the following:

1. Stable API v1 contract between ingress-facing services and compute-node runtime.
2. Release artifact discipline (immutable image tags, chart packaging, changelog/release notes).
3. Operationally mature relay behavior (timeouts, retries, backpressure, health probes).
4. Secret inventory and rotation process documented by token.place maintainers.
5. Environment-specific values files ready for Sugarkube routing.

## Release artifact expectations

Sugarkube onboarding assumes token.place publishes:

- OCI images with immutable tags (`sha-...`, semver, or equivalent).
- A Helm chart (or chart path) suitable for `helm upgrade --install` workflows.
- Values overlays for environment-specific routing and scale.
- Health/readiness endpoints used by `just tokenplace-validate` checks.

If any artifact is not finalized, keep `just` recipes parameterized and avoid hard-coding
names in Sugarkube.

## Namespace, release, and chart expectations

Sugarkube intentionally keeps token.place deploy details configurable.

Required operator decisions (per environment):

- Kubernetes namespace (for example `tokenplace`, `tokenplace-staging`, etc.).
- Helm release name.
- Chart reference (`oci://...` or local chart path).
- Ordered values files for base + environment overlays.

Use the token.place recipes in the root `justfile` with explicit parameters. When teams settle
on canonical names, promote them from operator notes into repo defaults in a follow-up PR.

## Environment mapping model

Recommended split:

- **dev**: fast iteration lane, lower SLA, can tolerate convenience tags if explicitly allowed.
- **staging**: production-like topology and ingress, immutable tag validation gate.
- **prod**: immutable-only promotions and explicit rollback procedure.

Compute-node workers can remain outside Sugarkube while relay/API ingress services run in-cluster.
This keeps heavy compute scaling independent from ingress/control-plane operations.

## Ownership boundaries

- **Sugarkube operators** own k3s cluster operations, ingress, Helm rollout/rollback mechanics,
  Cloudflare route health, and secret delivery plumbing.
- **token.place maintainers** own chart/schema correctness, service-level runtime behavior,
  API compatibility, and application-level incident response.

During incidents, split triage into:

1. Cluster/ingress path (Sugarkube).
2. Application behavior and upstream compute interactions (token.place).

## Operator workflow entry points

Use the following recipes after setting environment-specific parameters:

- `just tokenplace-status ...`
- `just tokenplace-deploy ...`
- `just tokenplace-upgrade ...`
- `just tokenplace-rollback ...`
- `just tokenplace-logs ...`
- `just tokenplace-validate ...`
- `just tokenplace-port-forward ...`

Recipe interfaces are intentionally generic so Sugarkube can onboard token.place without pretending
chart/release details are already fixed in this repository.
