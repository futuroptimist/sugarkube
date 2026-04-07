# token.place on k3s (staging)

## Purpose

Production-like validation environment for token.place release sign-off.

## Topology expectations

- Staging relay/API surfaces run on Sugarkube.
- Compute execution remains on external compute nodes, connected via secure API v1 interfaces.

## Prerequisites

- Valid staging kubeconfig and namespace access.
- Token.place chart and values contract finalized for staging.
- Cloudflare Tunnel route and DNS hostname in place.
- TLS issuer/cert automation available (for example cert-manager + ClusterIssuer).

## Deploy / upgrade / rollback patterns

```bash
just tokenplace-deploy env=staging namespace=<ns> release=<release> \
  chart=<chart-ref> values=<base-values.yaml,staging-values.yaml>
just tokenplace-upgrade env=staging namespace=<ns> release=<release> \
  chart=<chart-ref> values=<base-values.yaml,staging-values.yaml> tag=<immutable-tag>
just tokenplace-rollback namespace=<ns> release=<release> revision=<n>
```

## Validation checks

```bash
just tokenplace-status env=staging namespace=<ns> release=<release>
just tokenplace-validate env=staging namespace=<ns> release=<release> service=<svc>
just tokenplace-logs env=staging namespace=<ns> selector=<label-selector>
```

Recommended manual checks:

- ingress reachability and TLS validity for staging hostname
- `/healthz` and `/livez` (or token.place-defined health endpoints)
- relay-to-compute connectivity expectations for API v1 traffic

## Ingress / Cloudflare expectations

- Public staging hostname should route through Cloudflare Tunnel to Traefik.
- DNS, tunnel config, and TLS cert names must be environment-specific.

## Secrets and config guidance

- Use dedicated staging credentials and rotate regularly.
- Keep secret references explicit in values files without embedding raw secrets in Git.

## Operator notes

- Treat staging as promotion gate: prefer immutable tags and audited upgrades.
- Capture evidence (status/logs/health checks) before prod promotion.
