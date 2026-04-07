# token.place on k3s (prod)

## Purpose

Reliable production operation of token.place ingress-facing services on Sugarkube.

## Topology expectations

- Sugarkube hosts production relay/API ingress and Kubernetes-managed operational surfaces.
- External compute nodes provide heavy execution capacity outside the cluster.

## Prerequisites

- Approved release artifact (immutable tag) from staging sign-off.
- Production namespace/release/chart/values contract documented.
- Cloudflare Tunnel + DNS + TLS ready for production hostnames.
- Runbook owner on call for rollout and rollback windows.

## Deploy / upgrade / rollback patterns

```bash
just tokenplace-deploy env=prod namespace=<ns> release=<release> \
  chart=<chart-ref> values=<base-values.yaml,prod-values.yaml>
just tokenplace-upgrade env=prod namespace=<ns> release=<release> \
  chart=<chart-ref> values=<base-values.yaml,prod-values.yaml> tag=<immutable-tag>
just tokenplace-rollback namespace=<ns> release=<release> revision=<n>
```

## Validation checks

```bash
just tokenplace-status env=prod namespace=<ns> release=<release>
just tokenplace-validate env=prod namespace=<ns> release=<release> service=<svc>
just tokenplace-logs env=prod namespace=<ns> selector=<label-selector>
```

Production verification should include:

- endpoint health and latency checks
- ingress/TLS chain validation
- relay-to-compute path health across expected API v1 flows

## Ingress / Cloudflare expectations

- Production hostname routes through Cloudflare Tunnel to cluster ingress.
- Changes to DNS/tunnel policies require change control and rollback plan.

## Secrets and config guidance

- Strict least-privilege secrets with formal rotation policy.
- Environment isolation: never share prod secrets with lower environments.

## Operator notes and caveats

- Prefer upgrade windows with precomputed rollback revision.
- Keep runbooks and Just variables in sync as token.place chart contracts evolve.
