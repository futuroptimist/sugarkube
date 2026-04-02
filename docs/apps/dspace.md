# democratized.space (dspace) on Sugarkube

This guide covers steady-state DSPACE operations on Sugarkube: repeated staging and production
releases, optional preview deploys, and rollback-safe immutable tag usage.

The `justfile` exposes:

- generic Helm OCI helpers (`helm-oci-install`, `helm-oci-upgrade`) for any app; and
- DSPACE-focused helpers (`dspace-oci-deploy`, `dspace-oci-promote-prod`,
  `dspace-oci-redeploy`) that encode common operations.

## Environment topology

Current/future topology in this repo:

- **staging** (`env=staging`): HA on `sugarkube3`, `sugarkube4`, `sugarkube5`, served at
  `staging.democratized.space`.
- **prod** (`env=prod`): HA on `sugarkube0`, `sugarkube1`, `sugarkube2`, served at
  `democratized.space`.
- **dev** (`env=dev`, planned): single-node non-HA target on `sugarkube6`.

Values overlays:

- `docs/examples/dspace.values.dev.yaml`: shared defaults and `environment: dev` baseline.
- `docs/examples/dspace.values.staging.yaml`: staging ingress host/class overlay.
- `docs/examples/dspace.values.prod.yaml`: production apex ingress host/class overlay.
- `docs/examples/dspace.values.prod-subdomain.yaml`: optional production preview overlay for
  `prod.democratized.space` (canary/smoke tests when desired).

## Image tags and release terminology

- `main-latest`: mutable convenience tag for fast iteration (non-prod by default).
- `main-<shortsha>`: immutable commit-derived tag for promotion testing.
- `v<semver>` (for example `v3.0.1`, `v3.1.0`): immutable release tag for formal rollout and
  rollback points.

Use immutable tags for sign-off, production deploys, and rollback safety.

## Quick commands

```bash
# Staging deploy (recommended path for release validation):
just dspace-oci-deploy env=staging tag=main-<shortsha>

# Production deploy to apex (normal steady-state path):
just dspace-oci-promote-prod tag=v<semver>

# Equivalent explicit prod command:
just dspace-oci-deploy env=prod tag=v<semver>

# Optional preview/canary endpoint (not required for every release):
just dspace-oci-deploy-prod-subdomain tag=v<semver>

# Inspect release status:
just app-status namespace=dspace release=dspace
```

If you track an approved prod tag in `docs/apps/dspace.prod.tag`:

```bash
read_prod_tag() { sed -e 's/#.*$//' -e '/^[[:space:]]*$/d' docs/apps/dspace.prod.tag | head -n1 | tr -d '[:space:]'; }
just dspace-oci-promote-prod tag="$(read_prod_tag)"
```

## When to use each helper

- `helm-oci-install`: install-or-upgrade generic path (`helm upgrade --install`), no DSPACE-specific
  validation messaging.
- `helm-oci-upgrade`: upgrade existing release with `--reuse-values`, useful for quick/manual ops.
- `dspace-oci-deploy`: opinionated DSPACE deploy that requires an explicit immutable tag,
  applies correct env overlays, waits for rollout, and prints post-deploy checks.
- `dspace-oci-promote-prod`: thin wrapper for `dspace-oci-deploy env=prod`, using an explicit tag
  or `docs/apps/dspace.prod.tag`.
- `dspace-oci-deploy-prod-subdomain`: optional preview deploy for `prod.democratized.space`.
- `dspace-oci-redeploy`: emergency mutable-tag refresh path that forces a rollout restart.

## Generic Helm OCI examples

```bash
# First install (or idempotent install-or-upgrade):
just helm-oci-install \
  release=dspace namespace=dspace \
  chart=oci://ghcr.io/democratizedspace/charts/dspace \
  values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml \
  version_file=docs/apps/dspace.version \
  default_tag=main-latest

# Upgrade existing release to an immutable tag:
just helm-oci-upgrade \
  release=dspace namespace=dspace \
  chart=oci://ghcr.io/democratizedspace/charts/dspace \
  values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml \
  version_file=docs/apps/dspace.version \
  tag=main-<shortsha>

# Upgrade production with prod overlay:
just helm-oci-upgrade \
  release=dspace namespace=dspace \
  chart=oci://ghcr.io/democratizedspace/charts/dspace \
  values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.prod.yaml \
  version_file=docs/apps/dspace.version \
  tag=v<semver>
```

Notes:

- `version_file=docs/apps/dspace.version` pins the chart version by default; override with
  `version=<semver>` when needed.
- Environment overlays (`dev/staging/prod/prod-subdomain`) select ingress and app environment values;
  they do **not** represent release versions.
- `dspace-oci-deploy` rejects mutable tags such as `latest`/`main` to preserve reproducibility.

## Release/promotion pattern (evergreen)

Use this loop for each release:

1. Build and publish candidate image tags from `main` (for example `main-<shortsha>`).
2. Deploy to staging with `dspace-oci-deploy env=staging tag=...`.
3. Run smoke checks (`/config.json`, `/healthz`, `/livez`) on `staging.democratized.space`.
4. Optionally deploy same immutable tag to `prod.democratized.space` for preview/canary checks.
5. Promote approved immutable tag to apex with `dspace-oci-promote-prod` (or `dspace-oci-deploy env=prod`).
6. For rollback, redeploy the previous known-good immutable tag.

## Networking via Cloudflare Tunnel

Common public hostnames are:

- `https://staging.democratized.space` (staging)
- `https://democratized.space` (production apex)
- `https://prod.democratized.space` (optional preview endpoint)

For tunnel setup and DNS records, see `docs/cloudflare_tunnel.md`.

## Troubleshooting

- Retrieve combined app + ingress logs:

  ```bash
  just dspace-debug-logs-env env=staging
  just dspace-debug-logs-env env=prod
  ```

- Direct collector (if `KUBECONFIG` is already managed):

  ```bash
  just dspace-debug-logs namespace=dspace
  ```

- Live tail:

  ```bash
  kubectl -n dspace logs deploy/dspace --follow
  ```
