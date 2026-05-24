# DEPRECATED: local tokenplace-relay chart

This local chart is deprecated for steady-state Sugarkube deployments.

Use the token.place-owned OCI chart instead:

- Chart: `oci://ghcr.io/futuroptimist/charts/tokenplace`
- Release: `tokenplace`
- Namespace: `tokenplace`
- Values layering: `docs/examples/tokenplace.values.dev.yaml` plus staging/prod overlays

The local chart remains only as a temporary compatibility artifact while automation and docs
are migrated. New deployments and routine upgrades should not target `./apps/tokenplace-relay`.
