# k3s token.place runbook (prod)

Production runbook for token.place on Sugarkube.

## Purpose

- Stable public serving and controlled promotion from validated staging artifacts.
- Explicit operational ownership, auditability, and rollback readiness.

## Suggested defaults

- Environment: `prod`
- Namespace: `tokenplace` (configurable)
- Release: `tokenplace` (configurable)
- Hostname: `token.place` (or org-approved production host)

## Prerequisites

- Approved immutable tag already validated in staging
- Production values overlays reviewed
- Production secrets rotated/validated for release window
- Cloudflare + ingress + TLS paths verified

## Deploy / upgrade /rollback

```bash
TOKENPLACE_CHART='<chart-ref>' \
TOKENPLACE_VALUES_PROD='path/base.yaml,path/prod.yaml' \
just tokenplace-install env=prod tag=<immutable-tag>

just tokenplace-upgrade env=prod tag=<immutable-tag>

just tokenplace-rollback env=prod revision=<helm-revision>
```

## Validation checks

```bash
just tokenplace-status env=prod
TOKENPLACE_VALIDATE_URL='https://token.place' just tokenplace-validate env=prod
just tokenplace-logs namespace=tokenplace
```

## Cloudflare / ingress expectations

- Production DNS stays proxied through Cloudflare tunnel.
- Ingress host/annotation conventions match cluster policy.
- Certificate expiry and renewal are monitored.

## Secrets and config guidance

- Never commit production secrets to this repository.
- Keep secret names stable across releases where possible.
- Record secret ownership and last rotation in the security checklist.

## Operator caveats

- Perform upgrades inside approved maintenance windows unless emergency response
  requires immediate action.
- Keep prior known-good immutable tag and Helm revision handy before promotion.
