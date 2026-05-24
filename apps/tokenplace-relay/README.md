# Deprecated local tokenplace-relay chart

This local chart is deprecated for steady-state Sugarkube deployments.

Use the token.place-owned OCI chart instead:

- Chart: `oci://ghcr.io/futuroptimist/charts/tokenplace`
- Image: `ghcr.io/futuroptimist/tokenplace-relay`
- Release: `tokenplace`
- Namespace: `tokenplace`

Sugarkube-owned deploy layering lives under `docs/examples/`:

- `tokenplace.values.dev.yaml` (base/shared)
- `tokenplace.values.staging.yaml` (staging overlay)
- `tokenplace.values.prod.yaml` (prod overlay)

Keep this directory only for migration/reference until all remaining local-chart
wiring is removed.
