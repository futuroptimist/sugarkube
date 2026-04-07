# k3s token.place runbook (dev)

Use this runbook for `dev` token.place deployments on Sugarkube.

## Purpose

- Fast feedback for onboarding and integration changes.
- Validate chart wiring and values layering before staging.

## Topology intent (dev)

- Sugarkube hosts ingress/API-facing token.place components.
- External compute handles heavy runtime jobs.
- Routing and upstream credentials are dev-scoped.

## Prerequisites

- `kubectl`, `helm`, and `just` installed.
- Kubeconfig points to the dev environment cluster/context.
- token.place chart + image tag available.
- Dev values files prepared.

## Deploy / upgrade / rollback

```bash
just tokenplace-deploy \
  release=<release> namespace=<namespace> chart=<chart-ref> \
  values=<base-values>,<dev-values> version_file=<optional-version-file> \
  tag=<tag>
```

```bash
just tokenplace-upgrade \
  release=<release> namespace=<namespace> chart=<chart-ref> \
  values=<base-values>,<dev-values> version_file=<optional-version-file> \
  tag=<tag>
```

```bash
just tokenplace-rollback release=<release> namespace=<namespace> revision=<helm-revision>
```

## Validation

```bash
just tokenplace-status namespace=<namespace> release=<release>
just tokenplace-validate namespace=<namespace> release=<release> health_url=https://<dev-host>/<health>
```

```bash
just tokenplace-logs namespace=<namespace> selector=<label-selector>
```

## Local verification helper

```bash
just tokenplace-port-forward namespace=<namespace> service=<service> local_port=8080 remote_port=80
curl -fsS http://127.0.0.1:8080/<health>
```

## Ingress / Cloudflare expectations

- Dev hostname should be isolated from staging/prod.
- Cloudflare tunnel/DNS should target Traefik for dev hostnames.
- TLS secrets should not be shared across environments.

## Notes

- Dev may tolerate mutable convenience tags, but staging/prod should prefer immutable tags.
- Keep compute-node endpoint and auth config explicitly dev-scoped.
