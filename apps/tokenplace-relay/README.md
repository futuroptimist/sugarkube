# Deprecated local tokenplace-relay chart

This local chart is deprecated for steady-state Sugarkube deployments.

Use the token.place-owned OCI chart and Sugarkube-owned values overlays instead:

- Chart: `oci://ghcr.io/futuroptimist/charts/tokenplace`
- Base values: `docs/examples/tokenplace.values.dev.yaml`
- Staging overlay: `docs/examples/tokenplace.values.staging.yaml`
- Production overlay: `docs/examples/tokenplace.values.prod.yaml`

The local `apps/tokenplace-relay` chart remains temporarily for migration/reference
only and should not be preferred by new deployment workflows.
