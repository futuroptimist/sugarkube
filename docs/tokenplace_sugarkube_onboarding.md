# token.place Sugarkube onboarding

This onboarding guide defines the stable relay-only deployment contract for Sugarkube.

## Current deployment contract

- Sugarkube deploys only `relay.py`.
- No in-cluster backend/GPU service is required.
- External compute nodes stay external (`server.py`, desktop Tauri app, Windows PCs,
  Apple Silicon Macs, Raspberry Pi compute nodes).
- Runtime is single replica, single worker, in-memory relay state.
- In-memory state loss on pod death is currently accepted.

## Canonical release model

- Image: `ghcr.io/futuroptimist/tokenplace-relay`
- Chart: `oci://ghcr.io/futuroptimist/charts/tokenplace`
- Release: `tokenplace`
- Namespace: `tokenplace`
- Version pin: `docs/apps/tokenplace.version`
- Production approved tag pin: `docs/apps/tokenplace.prod.tag`

## Values model

- Base: `docs/examples/tokenplace.values.dev.yaml`
- Staging: `docs/examples/tokenplace.values.staging.yaml`
- Production: `docs/examples/tokenplace.values.prod.yaml`

## Environment defaults

- Staging host: `staging.token.place`
- Production host: `token.place`

## Standard operator commands

- Deploy/upgrade staging: `just tokenplace-oci-deploy env=staging tag=<immutable-tag>`
- Promote to production: `just tokenplace-oci-promote-prod tag=<approved-immutable-tag>`
- Redeploy existing release: `just tokenplace-oci-redeploy env=<staging|prod> tag=<immutable-tag>`
- Roll back Helm revision: `just tokenplace-rollback release=tokenplace namespace=tokenplace revision=<rev>`

## Required companion runbooks

- App operations: `docs/apps/tokenplace.md`
- Relay operations: `docs/apps/tokenplace-relay.md`
- Staging runbook: `docs/k3s-tokenplace-staging.md`
- Production runbook: `docs/k3s-tokenplace-prod.md`
