# k3s token.place runbook (staging)

Use this runbook for `staging` token.place deployments on Sugarkube.

## Purpose

- Release-candidate validation before production promotion.
- Full ingress + Cloudflare + TLS + API v1 behavior checks.

## Topology intent (staging)

- Sugarkube runs ingress/API-facing token.place services and relay integration points.
- External compute remains out-of-cluster but reachable over secured API v1 paths.
- Staging should mirror production architecture closely, with lower traffic volume.

## Prerequisites

- Chart/release wiring is defined for staging.
- Staging values overlays and secrets are reviewed.
- Cloudflare hostname routing to Traefik is configured.

## Deploy / upgrade / rollback

```bash
just tokenplace-deploy \
  release=<release> namespace=<namespace> chart=<chart-ref> \
  values=<base-values>,<staging-values> version_file=<optional-version-file> \
  tag=<immutable-tag>
```

```bash
just tokenplace-upgrade \
  release=<release> namespace=<namespace> chart=<chart-ref> \
  values=<base-values>,<staging-values> version_file=<optional-version-file> \
  tag=<immutable-tag>
```

```bash
just tokenplace-rollback release=<release> namespace=<namespace> revision=<helm-revision>
```

## Validation checks

```bash
just tokenplace-status namespace=<namespace> release=<release>
just tokenplace-validate namespace=<namespace> release=<release> health_url=https://<staging-host>/<health>
```

- Confirm ingress host and TLS certificate are ready.
- Confirm API v1 auth and external compute connectivity are healthy.
- Capture logs for relay/API components when validating release candidates.

```bash
just tokenplace-logs namespace=<namespace> selector=<label-selector>
```

## Cloudflare / ingress expectations

- Staging hostname is distinct from production hostname.
- Tunnel target points to Traefik (`kube-system` service).
- DNS records remain proxied in Cloudflare.

## Operator caveats

- Treat staging as promotion gate; avoid ad hoc value edits.
- Prefer immutable tags for reproducible rollback and forensic traceability.
