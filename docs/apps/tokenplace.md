# token.place on Sugarkube

This guide describes the intended token.place deployment model on Sugarkube once token.place
release artifacts are ready for formal onboarding.

For onboarding sequence and ownership boundaries, start with
[`docs/tokenplace_sugarkube_onboarding.md`](../tokenplace_sugarkube_onboarding.md).

## Intended topology

token.place on Sugarkube is expected to use a split model:

- **In-cluster (Sugarkube):** edge/API-facing components, ingress, relay-facing services,
  environment configuration, and operational controls.
- **External compute nodes:** heavier execution workloads that do not need to run on the Pi cluster.

This keeps Sugarkube focused on durable control-plane and ingress responsibilities while allowing
compute capacity to scale independently.

## Component placement guidance

Place on Sugarkube when a component:

- terminates external traffic,
- requires tight integration with k3s ingress/secrets,
- benefits from near-cluster observability and rollout controls.

Prefer external compute when a component:

- is CPU/GPU intensive,
- has bursty runtime needs,
- can tolerate network hop separation from the relay/API plane.

## Post-API-v1 secure deployment model

Expected steady state after API v1 convergence:

- all component-to-component communication uses authenticated API v1 paths,
- secrets are supplied via Kubernetes Secrets (or SOPS/Flux-managed equivalents),
- ingress is fronted by Cloudflare + Traefik,
- environment-specific values control hostnames, auth endpoints, and upstream compute routing.

## Prerequisites

- Sugarkube k3s cluster healthy for target environment (`dev`, `staging`, or `prod`).
- Cloudflare tunnel + DNS entries prepared for target token.place hostnames.
- Token.place chart and image artifacts available and documented.
- Environment values files prepared and reviewed.

## Core operational workflow

Use parameterized `just` recipes so unreconciled naming can be supplied at runtime:

1. Deploy/install:

   ```bash
   just tokenplace-deploy release=<release> namespace=<namespace> chart=<chart-ref> values=<base>,<env> tag=<tag>
   ```

2. Upgrade:

   ```bash
   just tokenplace-upgrade release=<release> namespace=<namespace> chart=<chart-ref> values=<base>,<env> tag=<tag>
   ```

3. Rollback:

   ```bash
   just tokenplace-rollback release=<release> namespace=<namespace> revision=<revision>
   ```

4. Validate:

   ```bash
   just tokenplace-validate namespace=<namespace> release=<release> health_url=https://<host>/<health-path>
   ```

5. Inspect and debug:

   ```bash
   just tokenplace-status namespace=<namespace> release=<release>
   just tokenplace-logs namespace=<namespace> selector=<label-selector>
   just tokenplace-port-forward namespace=<namespace> service=<service> local_port=8080 remote_port=80
   ```

## Cloudflare and ingress expectations

- Public access should terminate via Cloudflare and forward to Traefik.
- Hostnames should be environment-specific (`dev`, `staging`, `prod`) and documented in the env
  runbooks.
- cert-manager issuer and TLS secret naming should be explicit per environment.

## Secrets and config guidance

- Keep environment-specific secrets out of docs and commit history.
- Prefer immutable promotion tags for staging/prod.
- Keep shared defaults separate from env overlays to reduce accidental prod drift.

## Operator notes

- Do not assume namespace/release/chart naming until token.place onboarding finalizes.
- Keep recipes parameterized and runbooks explicit about what is fixed vs configurable.
- Use relay-specific guide ([`docs/apps/tokenplace-relay.md`](./tokenplace-relay.md)) for current relay-only operations.
