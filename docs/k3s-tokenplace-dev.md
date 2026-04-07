# k3s token.place (dev)

Development runbook for token.place on Sugarkube.

## Scope

- Environment: `dev`
- Goal: safe iteration and integration validation
- SLA posture: non-production

## Topology expectations

- Sugarkube hosts ingress/API and relay services.
- External compute nodes provide runtime workloads.
- API contract is API v1.

## Prerequisites

- kubeconfig points to dev cluster/context.
- token.place chart/release/value files prepared.
- Dev hostname/DNS and ingress route configured.

## Deploy / upgrade / rollback

```bash
just tokenplace-deploy env=dev chart=<chart> namespace=<ns> release=<release> values=<base,dev> tag=<tag>
just tokenplace-upgrade env=dev chart=<chart> namespace=<ns> release=<release> values=<base,dev> tag=<tag>
just tokenplace-rollback namespace=<ns> release=<release> revision=<rev>
```

## Validation checks

```bash
just tokenplace-status namespace=<ns> release=<release>
just tokenplace-validate namespace=<ns> release=<release> host=https://<dev-host>
just tokenplace-port-forward namespace=<ns> resource=svc/<service> local_port=8080 remote_port=80
```

## Cloudflare / ingress

- Dev may use internal-only ingress or restricted Cloudflare routes.
- Keep hostnames clearly separated from staging/prod.

## Secrets/config

- Use dev-scoped secrets only.
- Never reuse production credentials in dev.

## Caveats

- Mutable tags can be allowed in dev only when explicitly documented.
- If release wiring changes frequently, prefer scriptable parameter files rather than ad-hoc commands.
