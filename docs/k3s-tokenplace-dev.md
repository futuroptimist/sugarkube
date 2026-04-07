# k3s token.place runbook (dev)

Development environment runbook for token.place on Sugarkube.

## Purpose

- Fast iteration and integration testing.
- Accepts mutable tags when needed, but immutable tags are still preferred.

## Suggested defaults

- Environment: `dev`
- Namespace: `tokenplace` (configurable)
- Release: `tokenplace` (configurable)
- Hostname: `dev.token.place` (example placeholder)

## Prerequisites

- `just kubeconfig-env env=dev`
- token.place chart reference available (`TOKENPLACE_CHART` or `chart=`)
- dev values overlays available

## Deploy / upgrade / rollback

```bash
TOKENPLACE_CHART='<chart-ref>' \
TOKENPLACE_VALUES_DEV='path/base.yaml,path/dev.yaml' \
just tokenplace-install env=dev tag=<tag>

just tokenplace-upgrade env=dev tag=<tag>

just tokenplace-rollback env=dev revision=<helm-revision>
```

## Validation

```bash
just tokenplace-status env=dev
TOKENPLACE_VALIDATE_URL='https://dev.token.place' just tokenplace-validate env=dev
just tokenplace-logs namespace=tokenplace
```

## Local verification helper

```bash
just tokenplace-port-forward-app namespace=tokenplace service=<service-name> local_port=5010 remote_port=80
curl -fsS http://127.0.0.1:5010/healthz
```

## Notes

- Dev may point at non-production compute nodes.
- Keep credentials/test data separate from staging/prod.
