# token.place on Sugarkube

This runbook defines the **target operating model** for onboarding token.place onto
Sugarkube once token.place-side migration work is complete.

## Intended topology

Sugarkube hosts the internet-facing and control-plane-facing token.place pieces,
while heavy compute remains external.

- **On Sugarkube (k3s):** ingress-facing token.place service(s), relay/control
  surface, environment routing, and app-adjacent observability.
- **External compute nodes:** model/runtime workers and hardware-dependent
  execution where GPU/accelerator locality matters.
- **Boundary:** relay-to-compute communication is authenticated, encrypted, and
  constrained to API v1 contracts.

## Components expected on Sugarkube

The exact chart structure may evolve, but onboarding assumes these categories:

1. Token.place API/edge workload(s)
2. Relay component(s) where cluster-side routing is required
3. Kubernetes-native ingress, TLS, and service discovery config
4. Optional in-cluster queues/caches only when app architecture requires them

Use parameterized just recipes so chart/release wiring can be finalized without
rewriting operator workflows.

## Secure post-API-v1 deployment model

- All relay↔compute traffic uses API v1 with explicit auth material.
- Secrets are injected through Kubernetes secret references, not committed YAML.
- Environment overlays control routing and non-secret config.
- Production releases use immutable tags and rollback via Helm history.

## Prerequisites

- k3s cluster reachable with `kubectl` and `helm`
- Traefik ingress and cert-manager functioning
- Cloudflare tunnel + DNS in place for environment hostnames
- token.place chart and values overlays published or available locally
- Secrets provisioned out-of-band (e.g., `kubectl create secret ...`)

## Deployment and lifecycle workflows

```bash
# Install (first deployment in an env)
just tokenplace-install env=staging chart='<chart-ref>' \
  values='path/base.yaml,path/staging.yaml' tag=<immutable-tag>

# Upgrade (existing release)
just tokenplace-upgrade env=staging chart='<chart-ref>' \
  values='path/base.yaml,path/staging.yaml' tag=<immutable-tag>

# Rollback
just tokenplace-rollback env=staging revision=<helm-revision>

# Status and validation
just tokenplace-status env=staging
TOKENPLACE_VALIDATE_URL='https://staging.token.place' just tokenplace-validate env=staging

# Logs and local verification helpers
just tokenplace-logs namespace=tokenplace
just tokenplace-port-forward-app namespace=tokenplace service=<service-name> local_port=5010 remote_port=80
```

## Cloudflare and ingress expectations

- One hostname per environment (`dev`, `staging`, `prod`) mapped via Cloudflare tunnel.
- Ingress class should match cluster standard (`traefik` unless explicitly changed).
- TLS certificates managed by cert-manager with environment-specific secrets.
- DNS records should remain proxied unless incident handling requires temporary bypass.

## Secrets and config guidance

Standardize in docs/reviews:

- Secret names, key names, and owning team
- Rotation interval and emergency rotation playbook
- Minimum required env vars per component

Keep configurable in deployment:

- Release name, namespace, chart URL/path
- Values overlays and hostnames
- Optional feature flags for environment-specific behavior

## Operator caveats

- Do not assume relay-only topology for all future token.place releases.
- Treat compute nodes as separately managed infrastructure; avoid coupling their
  lifecycle to k3s rollout cadence.
- Rehearse rollback and smoke tests in staging before prod promotion.
- Keep this guide aligned with [tokenplace_sugarkube_onboarding.md](../tokenplace_sugarkube_onboarding.md)
  and environment runbooks.
