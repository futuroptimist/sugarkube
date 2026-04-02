# democratized.space (dspace) on Sugarkube

This guide covers **steady-state dspace operations** on Sugarkube: repeatable deploys,
upgrades, promotions, and rollbacks using immutable image tags.

The `justfile` exposes both:

- generic Helm OCI helpers (`helm-oci-install`, `helm-oci-upgrade`) for any app; and
- dspace-specific helpers for immutable deploys and production promotion
  (`dspace-oci-deploy`, `dspace-oci-promote-prod`, `dspace-oci-redeploy`).

## Environment topology and values overlays

dspace values are layered so base defaults stay separate from environment routing.

- `docs/examples/dspace.values.dev.yaml`: shared defaults, intended for future `env=dev`
  deployments.
- `docs/examples/dspace.values.staging.yaml`: staging ingress host/class overlay.
- `docs/examples/dspace.values.prod.yaml`: production apex ingress overlay.
- `docs/examples/dspace.values.prod-subdomain.yaml`: optional preview/canary overlay for
  `prod.democratized.space`.

Current/target topology:

- **staging (live, HA):** `env=staging` on `sugarkube3`, `sugarkube4`, `sugarkube5`,
  public host `staging.democratized.space`.
- **prod (live, HA):** `env=prod` on `sugarkube0`, `sugarkube1`, `sugarkube2`,
  public host `democratized.space`.
- **dev (planned, non-HA):** `env=dev` on `sugarkube6` (single-node future environment).

## Tagging model (evergreen releases)

Use tags by purpose:

- **Convenience/mutable tags** for fast iteration in non-prod (for example `main-latest`).
- **Immutable deploy tags** for sign-off, promotion, and rollback (for example
  `main-<shortsha>`, `3.0.1`, `3.1.0`).
- In this operational guide, `main` is the normal integration line that produces
  DSPACE-derived image tags (for example `main-<shortsha>`).
- If the DSPACE repo uses release branches, keep them short-lived stabilization branches,
  not long-lived environment branches.

Environment overlays (`dev`/`staging`/`prod`) decide host/routing. Image tags decide the
release version. Keep those concerns separate.

## Quickstart

```bash
# Immutable staging deploy (recommended for release validation)
just dspace-oci-deploy env=staging tag=main-<shortsha>

# Immutable production deploy (reads docs/apps/dspace.prod.tag if tag is omitted)
just dspace-oci-promote-prod tag=3.1.0

# Optional preview/canary endpoint (prod.democratized.space)
just dspace-oci-deploy-prod-subdomain tag=main-<shortsha>

# Check pods/ingress/status
just app-status namespace=dspace release=dspace
```

## When to use each helper

- `helm-oci-install`: install-or-upgrade path (uses `helm upgrade --install`), useful when a
  release may not exist yet.
- `helm-oci-upgrade`: upgrade-only path with `--reuse-values`, useful for routine bumps on an
  existing release.
- `dspace-oci-deploy`: opinionated dspace wrapper that requires an explicit immutable tag,
  applies the correct values chain for `env=dev|staging|prod`, and waits for rollout.
- `dspace-oci-promote-prod`: production convenience wrapper around
  `dspace-oci-deploy env=prod`, reading `docs/apps/dspace.prod.tag` when `tag=` is omitted.
- `dspace-oci-redeploy`: force-refresh path for already-deployed tags (especially mutable tags)
  by running a Helm upgrade and rollout restart.

## Generic Helm OCI examples

```bash
# Install-or-upgrade staging with mutable convenience tag
just helm-oci-install \
  release=dspace namespace=dspace \
  chart=oci://ghcr.io/democratizedspace/charts/dspace \
  values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml \
  version_file=docs/apps/dspace.version \
  default_tag=main-latest

# Upgrade staging to an immutable build
just helm-oci-upgrade \
  release=dspace namespace=dspace \
  chart=oci://ghcr.io/democratizedspace/charts/dspace \
  values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml \
  version_file=docs/apps/dspace.version \
  tag=main-<shortsha>

# Upgrade prod directly to a signed-off immutable tag
just helm-oci-upgrade \
  release=dspace namespace=dspace \
  chart=oci://ghcr.io/democratizedspace/charts/dspace \
  values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.prod.yaml \
  version_file=docs/apps/dspace.version \
  tag=3.1.0
```

Notes:

- `version_file=docs/apps/dspace.version` keeps chart version pinning centralized.
- For prod, prefer immutable tags and persist the approved one in `docs/apps/dspace.prod.tag`.
- `dspace-oci-deploy` rejects mutable tags (`latest`, `main`) by design.

## Evergreen release/promotion flow

1. Build and publish candidate image tags from `main` (for example `main-<shortsha>` plus
   optional `main-latest`).
2. Deploy immutable candidate to staging:

   ```bash
   just dspace-oci-deploy env=staging tag=main-<shortsha>
   ```

3. Verify staging (`config.json`, `healthz`, `livez`) at
   `https://staging.democratized.space`.

   ```bash
   curl -fsS https://staging.democratized.space/config.json | jq .
   ```

   ```bash
   curl -fsS https://staging.democratized.space/healthz | jq .
   ```

   ```bash
   curl -fsS https://staging.democratized.space/livez | jq .
   ```

4. Promote the approved immutable tag to production apex:

   ```bash
   just dspace-oci-promote-prod tag=main-<shortsha>
   # or semver tag once released
   just dspace-oci-promote-prod tag=3.1.0
   ```

   Then verify production:

   ```bash
   curl -fsS https://democratized.space/config.json | jq .
   ```

   ```bash
   curl -fsS https://democratized.space/healthz | jq .
   ```

   ```bash
   curl -fsS https://democratized.space/livez | jq .
   ```

5. Keep rollback simple by redeploying the prior immutable tag.

Optional only: use `dspace-oci-deploy-prod-subdomain` for preview/canary checks at
`https://prod.democratized.space` when you explicitly want a pre-apex validation endpoint.
It is not part of the default required deploy/promotion path.

## Networking via Cloudflare Tunnel

This guide assumes public ingress is exposed via Cloudflare Tunnel.

Typical hostnames:

- staging: `https://staging.democratized.space`
- preview/canary (optional): `https://prod.democratized.space`
- production apex: `https://democratized.space`

For tunnel and DNS setup details, see [Cloudflare Tunnel docs](../cloudflare_tunnel.md).

## Troubleshooting

- Collect dspace + ingress logs with environment-aware helper:

  ```bash
  just dspace-debug-logs-env env=staging
  just dspace-debug-logs-env env=prod
  ```

- Inspect Helm release state:
  - `helm -n dspace status dspace`
  - `helm -n dspace get values dspace`
- Inspect Kubernetes objects:
  - `kubectl -n dspace get ingress,pods,svc`
  - `kubectl -n dspace describe ingress dspace`
