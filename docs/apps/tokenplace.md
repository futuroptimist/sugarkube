# token.place on Sugarkube

This page defines how token.place fits onto Sugarkube once token.place runtime and API v1
migration are complete.

## Intended topology

token.place is expected to run in a split topology:

- **On Sugarkube (k3s):** ingress-facing services, relay/API surface, operational control plane
  integration, and Kubernetes-managed observability hooks.
- **External compute nodes:** heavy compute runtimes and node-local execution workers.

Sugarkube is the control-plane-aligned hosting layer, not the full compute substrate.

## Component placement model

Components that typically belong on Sugarkube:

- Public ingress entrypoint(s) behind Traefik + Cloudflare Tunnel.
- Relay and coordination services that require stable DNS/TLS and cluster lifecycle management.
- Environment-scoped config maps/secrets used by token.place control services.

Components that typically stay external:

- GPU-heavy or high-throughput worker pools.
- Specialized compute runtimes managed outside Sugarkube's k3s lifecycle.

## Secure post-API-v1 model

After API v1 convergence, operations should assume:

- Authenticated relay↔compute traffic with explicit token/credential boundaries.
- Least-privilege secrets per environment and component.
- Immutable, auditable releases for staging sign-off and production promotion.

## Runbooks

- Onboarding contract: [../tokenplace_sugarkube_onboarding.md](../tokenplace_sugarkube_onboarding.md)
- Dev runbook: [../k3s-tokenplace-dev.md](../k3s-tokenplace-dev.md)
- Staging runbook: [../k3s-tokenplace-staging.md](../k3s-tokenplace-staging.md)
- Prod runbook: [../k3s-tokenplace-prod.md](../k3s-tokenplace-prod.md)
- Relay-specific current guide: [tokenplace-relay.md](tokenplace-relay.md)

## Operator commands

Use parameterized recipes until final chart/release wiring is locked:

```bash
just tokenplace-status env=staging namespace=<ns> release=<release>
just tokenplace-deploy env=staging namespace=<ns> release=<release> \
  chart=<chart-ref> values=<values1.yaml,values2.yaml>
just tokenplace-upgrade env=staging namespace=<ns> release=<release> \
  chart=<chart-ref> values=<values1.yaml,values2.yaml> tag=<immutable-tag>
just tokenplace-rollback namespace=<ns> release=<release> revision=<helm-revision>
just tokenplace-validate env=staging namespace=<ns> release=<release> service=<svc>
just tokenplace-logs env=staging namespace=<ns> selector=<label-selector>
just tokenplace-port-forward namespace=<ns> service=<svc> local_port=8080
```
