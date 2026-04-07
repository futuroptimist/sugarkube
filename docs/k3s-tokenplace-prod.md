# k3s token.place runbook (prod)

Use this runbook for `prod` token.place deployments on Sugarkube.

## Purpose

- Safe production deployment, validation, and rollback.
- Preserve availability with explicit promotion and incident-response workflow.

## Topology intent (prod)

- Sugarkube hosts production ingress/API-facing token.place services.
- External compute nodes execute heavy workloads and are reached through secured API v1 links.
- Public hostnames route through Cloudflare to Traefik ingress.

## Prerequisites

- Staging validation completed for the target immutable tag.
- Production values overlays and secrets approved.
- Rollback revision identified before upgrade begins.

## Deploy / upgrade / rollback

```bash
just tokenplace-deploy \
  release=<release> namespace=<namespace> chart=<chart-ref> \
  values=<base-values>,<prod-values> version_file=<optional-version-file> \
  tag=<approved-immutable-tag>
```

```bash
just tokenplace-upgrade \
  release=<release> namespace=<namespace> chart=<chart-ref> \
  values=<base-values>,<prod-values> version_file=<optional-version-file> \
  tag=<approved-immutable-tag>
```

```bash
# List history first, then rollback if needed.
helm -n <namespace> history <release>
just tokenplace-rollback release=<release> namespace=<namespace> revision=<known-good-revision>
```

## Validation checks

```bash
just tokenplace-status namespace=<namespace> release=<release>
just tokenplace-validate namespace=<namespace> release=<release> health_url=https://<prod-host>/<health>
```

```bash
just tokenplace-logs namespace=<namespace> selector=<label-selector>
```

## Cloudflare / ingress expectations

- Production hostname and TLS secret names are stable and documented.
- Cloudflare tunnel routes only expected production hosts.
- Any emergency DNS/ingress change is logged in outage documentation.

## Secrets/config guidance

- Use production-scoped credentials only; never reuse lower-environment keys.
- Keep secret rotation cadence aligned with Sugarkube security checklist.
- Apply least-privilege API tokens for DNS/tunnel automation.

## Operator notes and caveats

- Avoid mutable tags in production.
- Keep a known-good rollback revision and artifact digest recorded for each deploy.
- If rollout behavior diverges from staging, pause further promotions and capture diagnostics.
