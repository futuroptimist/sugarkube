# k3s token.place (prod)

Production runbook for token.place on Sugarkube.

## Scope

- Environment: `prod`
- Goal: stable public operations with controlled change windows
- SLA posture: production

## Topology expectations

- Sugarkube hosts token.place ingress/API and relay/control-plane services.
- External compute nodes supply runtime capacity and can scale separately.
- API v1 is mandatory for compatibility and support.

## Prerequisites

- Production kubeconfig/context verified.
- Approved immutable image tag selected from staging validation.
- Production DNS/Cloudflare route and TLS posture ready.
- Rollback revision/tag identified before deployment starts.

## Deploy / upgrade / rollback

```bash
just tokenplace-deploy env=prod chart=<chart> namespace=<ns> release=<release> values=<base,prod> tag=<immutable-tag>
just tokenplace-upgrade env=prod chart=<chart> namespace=<ns> release=<release> values=<base,prod> tag=<immutable-tag>
just tokenplace-rollback namespace=<ns> release=<release> revision=<rev>
```

## Validation checks

```bash
just tokenplace-status namespace=<ns> release=<release>
just tokenplace-validate namespace=<ns> release=<release> host=https://<prod-host>
just tokenplace-logs namespace=<ns> selector='app.kubernetes.io/instance=<release>'
```

## Cloudflare / ingress

- Cloudflare hostnames should map deterministically to Traefik entrypoints.
- Monitor cert status and ingress events immediately after each upgrade.

## Secrets/config

- Production secrets must be independently stored, audited, and rotated.
- Keep change records for secret rotation and config toggles.

## Caveats

- Do not deploy mutable tags in production.
- Keep rollback mechanics tested in staging before production use.
