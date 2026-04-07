# token.place on Sugarkube

This guide defines the intended **operating model** for token.place on Sugarkube after
secure API v1 convergence. It complements the environment runbooks:

- [token.place dev runbook](../k3s-tokenplace-dev.md)
- [token.place staging runbook](../k3s-tokenplace-staging.md)
- [token.place production runbook](../k3s-tokenplace-prod.md)
- [token.place Sugarkube onboarding](../tokenplace_sugarkube_onboarding.md)

## Intended topology

Sugarkube hosts ingress-facing and control-plane components; compute stays external.

- In-cluster (Sugarkube):
  - token.place ingress/API services
  - token.place relay/control services
  - observability hooks (logs/events/health checks)
- External compute nodes:
  - model/runtime workers
  - high-variance CPU/GPU tasks

This split keeps Sugarkube focused on stable routing, deploy safety, and operations.

## Deployment model (post API v1)

- API v1 is the only supported public contract for Sugarkube onboarding.
- Deployments use Helm with values layering (`base + env overlay`).
- Staging and production should use immutable image tags.
- Rollback uses Helm revision history or redeploying a previous immutable tag.

## Prerequisites

- Healthy k3s cluster with working kubeconfig and Helm.
- Traefik ingress path verified.
- Cloudflare Tunnel/DNS configured for selected token.place hosts.
- token.place chart, release naming, and values files prepared by token.place maintainers.
- Secrets available via your chosen secure delivery workflow.

## Standard workflows

The `justfile` intentionally provides parameterized recipes instead of hard-coded app wiring:

- Status/health overview: `just tokenplace-status namespace=<ns> release=<release>`
- Install/deploy: `just tokenplace-deploy chart=<chart> namespace=<ns> release=<release> values=<files> ...`
- Upgrade: `just tokenplace-upgrade chart=<chart> namespace=<ns> release=<release> values=<files> ...`
- Rollback: `just tokenplace-rollback namespace=<ns> release=<release> revision=<rev>`
- Logs: `just tokenplace-logs namespace=<ns> selector='<label-selector>'`
- Validation: `just tokenplace-validate namespace=<ns> release=<release> host=<https://host>`
- Local verify helper: `just tokenplace-port-forward namespace=<ns> resource=<svc/name> ...`

## Cloudflare / ingress expectations

- Cloudflare Tunnel should route token.place hostnames to Traefik.
- TLS and certificate automation should follow the existing Sugarkube ingress pattern.
- Staging and production hosts should be separated clearly (no shared DNS target by mistake).

See [cloudflare_tunnel.md](../cloudflare_tunnel.md) for tunnel baseline guidance.

## Secrets and configuration guidance

Keep application secrets out of Git. Prefer:

- secret managers or sealed-secret workflows,
- per-environment secret scopes,
- rotation records in operational change logs.

At minimum, document where each required token.place secret is sourced, who owns it,
and how to rotate it without downtime.

## Operator notes and caveats

- Sugarkube is intentionally generic; avoid over-coupling core tooling to token.place internals.
- If chart/release names are unsettled, keep using parameterized `just` inputs.
- Require explicit host checks in staging and prod before promotions.
- Treat compute-node incidents and ingress incidents as separate triage tracks.
