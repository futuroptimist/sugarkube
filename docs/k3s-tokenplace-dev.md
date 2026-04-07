# token.place on k3s (dev)

## Purpose

Development environment for fast integration testing and deployment rehearsal.

## Topology expectations

- k3s hosts ingress-facing token.place services.
- External compute nodes remain outside Sugarkube and connect through approved relay paths.

## Prerequisites

- k3s cluster reachable with valid `KUBECONFIG`.
- Helm and kubectl installed.
- token.place chart/release contract available (chart, release, namespace, values files).
- Cloudflare/TLS details prepared if public ingress is used in dev.

## Deploy / upgrade / rollback patterns

```bash
just tokenplace-deploy env=dev namespace=<ns> release=<release> \
  chart=<chart-ref> values=<base-values.yaml,dev-values.yaml>
just tokenplace-upgrade env=dev namespace=<ns> release=<release> \
  chart=<chart-ref> values=<base-values.yaml,dev-values.yaml> tag=<tag>
just tokenplace-rollback namespace=<ns> release=<release> revision=<n>
```

## Validation checks

```bash
just tokenplace-status env=dev namespace=<ns> release=<release>
just tokenplace-validate env=dev namespace=<ns> release=<release> service=<svc>
just tokenplace-port-forward namespace=<ns> service=<svc> local_port=8080
```

## Ingress / Cloudflare expectations

- Prefer internal-only ingress in early dev where possible.
- If Cloudflare is enabled, use environment-specific hostnames and isolated credentials.

## Secrets and config guidance

- Use dev-scoped secrets only; never reuse staging/prod credentials.
- Keep secrets external to docs and version control; use existing Sugarkube secret workflows.

## Operator notes

- Mutable image tags are acceptable only for short-lived developer iteration.
- Record any interface changes so staging/prod runbooks stay aligned.
