# k3s token.place (staging)

Staging runbook for token.place on Sugarkube.

## Scope

- Environment: `staging`
- Goal: production-like validation and release gating
- SLA posture: pre-production

## Topology expectations

- Sugarkube hosts ingress/API and relay services.
- External compute nodes provide runtime workloads.
- API v1 behavior should match production assumptions.

## Prerequisites

- kubeconfig points to staging cluster/context.
- Immutable token.place image tags available.
- Staging values overlay and hostname routing validated.

## Deploy / upgrade / rollback

```bash
just tokenplace-deploy env=staging chart=<chart> namespace=<ns> release=<release> values=<base,staging> tag=<immutable-tag>
just tokenplace-upgrade env=staging chart=<chart> namespace=<ns> release=<release> values=<base,staging> tag=<immutable-tag>
just tokenplace-rollback namespace=<ns> release=<release> revision=<rev>
```

## Validation checks

```bash
just tokenplace-status namespace=<ns> release=<release>
just tokenplace-validate namespace=<ns> release=<release> host=https://<staging-host>
just tokenplace-logs namespace=<ns> selector='app.kubernetes.io/instance=<release>'
```

## Cloudflare / ingress

- Staging host should be distinct and never reused for prod.
- Validate cert provisioning and HTTP route behavior before promotion.

## Secrets/config

- Use staging-specific credentials and quotas.
- Confirm secrets are rotated independently from production.

## Caveats

- Staging is the sign-off lane for immutable tags.
- Promotion to prod should only happen after explicit validation evidence.
