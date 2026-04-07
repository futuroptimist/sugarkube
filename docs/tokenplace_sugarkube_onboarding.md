# token.place Sugarkube onboarding

This guide prepares Sugarkube to run `token.place` as a first-class workload once token.place
release artifacts and chart wiring are finalized.

It is intentionally a **deployment-preparation** runbook: it defines stable interfaces,
ownership, and operational shape without pretending that chart/release identifiers are immutable
before the token.place onboarding cutover is complete.

## Why token.place belongs on Sugarkube

- Sugarkube already provides a repeatable k3s + ingress + Cloudflare operating model.
- token.place already has relay operations on Sugarkube (`docs/apps/tokenplace-relay.md`), so this
  onboarding extends an existing operational pattern instead of introducing a new stack.
- Sugarkube gives a consistent operator interface (`just` + runbooks) across `dev`, `staging`, and
  `prod`, reducing drift during promotion and rollback.

## Preconditions before onboarding

Before onboarding the full token.place workload, confirm token.place has completed:

1. Shared desktop/server compute-node runtime.
2. Desktop parity with `server.py` behavior.
3. Operationally mature relay service.
4. Secure API v1 convergence across token.place components.
5. Release artifact publication (container images + Helm chart) suitable for repeatable deployment.

If any precondition is incomplete, keep using relay-only operations and postpone full onboarding.

## Release artifact expectations

During onboarding, token.place should provide:

- A Helm chart (OCI or repository path) that supports environment-specific values overlays.
- Versioned chart metadata (or pinned chart digest/version).
- Container image tags suitable for promotion (prefer immutable tags).
- Health endpoints and readiness/liveness semantics documented for operator validation.

## Expected Sugarkube wiring (standardized vs configurable)

Standardized in Sugarkube:

- Task-runner interface (recipes in `justfile`):
  - `tokenplace-deploy`
  - `tokenplace-upgrade`
  - `tokenplace-rollback`
  - `tokenplace-status`
  - `tokenplace-logs`
  - `tokenplace-validate`
  - `tokenplace-port-forward`
- Environment runbooks:
  - `docs/k3s-tokenplace-dev.md`
  - `docs/k3s-tokenplace-staging.md`
  - `docs/k3s-tokenplace-prod.md`

Configurable per onboarding cutover:

- Namespace, release name, chart location, values files, chart version pin, and image tag strategy.
- Ingress hosts and Cloudflare DNS/tunnel mapping.
- Which token.place components run in-cluster vs on external compute nodes.

## Environment mapping

- `dev`: fast iteration, lower blast radius, relaxed SLOs.
- `staging`: pre-production integration and release validation.
- `prod`: public workload, strict rollback and change-control discipline.

Use the environment-specific runbooks for concrete command patterns.

## Ownership boundaries

- **token.place team** owns chart/app semantics, release artifacts, and component-level config.
- **Sugarkube operators** own cluster lifecycle, ingress/tunnel plumbing, secret distribution,
  deployment execution, and rollback orchestration.
- Shared responsibility: production cutover sequencing, health-gate criteria, and incident
  response.

## App catalog and related docs

- App overview: `docs/apps/tokenplace.md`
- Relay-specific operations: `docs/apps/tokenplace-relay.md`
- Environment runbooks:
  - `docs/k3s-tokenplace-dev.md`
  - `docs/k3s-tokenplace-staging.md`
  - `docs/k3s-tokenplace-prod.md`

## Baseline command templates

Set values explicitly per environment to avoid hidden assumptions:

```bash
just tokenplace-deploy \
  release=<release> namespace=<namespace> chart=<chart-ref> \
  values=<base-values>,<env-values> version_file=<optional-version-file> \
  tag=<image-tag>
```

```bash
just tokenplace-upgrade \
  release=<release> namespace=<namespace> chart=<chart-ref> \
  values=<base-values>,<env-values> version_file=<optional-version-file> \
  tag=<image-tag>
```

```bash
just tokenplace-rollback release=<release> namespace=<namespace> revision=<helm-revision>
```
