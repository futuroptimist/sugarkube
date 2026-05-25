# Deprecated local chart: tokenplace-relay

This local Helm chart is **deprecated** for steady-state Sugarkube deployments.

Use the token.place-owned OCI chart instead:

- Chart: `oci://ghcr.io/futuroptimist/charts/tokenplace`
- Image: `ghcr.io/futuroptimist/tokenplace-relay`
- Release: `tokenplace`
- Namespace: `tokenplace`

Sugarkube-owned deployment values and version pins now live under:

- `docs/examples/tokenplace.values.dev.yaml`
- `docs/examples/tokenplace.values.staging.yaml`
- `docs/examples/tokenplace.values.prod.yaml`
- `docs/apps/tokenplace.version`
- `docs/apps/tokenplace.prod.tag`

Keep this directory only for migration/reference until remaining legacy wiring is
fully removed.
