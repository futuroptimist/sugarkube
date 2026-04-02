# democratized.space (dspace) on Sugarkube

This guide documents **steady-state dspace operations** on Sugarkube after the v3 launch period.
Use it for repeated staging/prod releases, rollbacks, and emergency redeploys.

## Environment topology

Current and planned dspace environments:

- **staging** (`env=staging`): live HA environment on `sugarkube3`, `sugarkube4`, `sugarkube5`,
  served at `https://staging.democratized.space`.
- **prod** (`env=prod`): live HA environment on `sugarkube0`, `sugarkube1`, `sugarkube2`,
  served at `https://democratized.space`.
- **dev** (`env=dev`): planned future non-HA environment on `sugarkube6`.

`main` is the default dspace branch. The old `v3` branch cutover flow is no longer used.

## Values overlays and what they mean

Values files define environment-specific settings (mainly ingress host/class):

- `docs/examples/dspace.values.dev.yaml`: base defaults (`environment: dev`)
- `docs/examples/dspace.values.staging.yaml`: staging overlay (`environment: staging`,
  `host: staging.democratized.space`)
- `docs/examples/dspace.values.prod.yaml`: production overlay (`environment: prod`,
  `host: democratized.space`)
- `docs/examples/dspace.values.prod-subdomain.yaml`: optional production preview/canary overlay
  (`environment: prod`, `host: prod.democratized.space`)

Use environment overlays to choose destination hostnames. Use image tags to choose release version.

## Tags: convenience vs immutable

- **Convenience tags** (for quick refreshes):
  - `main-latest`
- **Immutable deploy tags** (for sign-off, promotion, and rollback):
  - `main-<shortsha>`
  - `v<semver>` (for example `v3.0.1`, `v3.1.0`)

For staging/prod sign-off and rollback safety, deploy immutable tags.

## Command reference

### dspace-specific wrappers

- `just dspace-oci-deploy env=<dev|staging|prod> tag=<immutable-tag>`
  - install-or-upgrade flow for dspace
  - rejects mutable tags (for example `latest`, `main`)
  - waits for rollout and prints verification commands
- `just dspace-oci-promote-prod tag=<immutable-tag>`
  - alias for prod promotion (reads `docs/apps/dspace.prod.tag` when `tag` is omitted)
- `just dspace-oci-deploy-prod-subdomain tag=<immutable-tag>`
  - optional preview/canary deploy to `prod.democratized.space`
- `just dspace-oci-redeploy env=<staging|prod|dev> [tag=...]`
  - emergency restart path that reuses values and forces pod recycle
  - defaults to `main-latest` outside prod; prod requires immutable tag (explicit or
    `docs/apps/dspace.prod.tag`)

### generic Helm OCI wrappers

- `just helm-oci-install ...` → install or upgrade
- `just helm-oci-upgrade ...` → upgrade with `--reuse-values`

Use generic wrappers when you need custom chart/value wiring. Use dspace wrappers for standard
operator workflows.

## Quickstart

```bash
# Staging immutable release deploy (recommended)
just dspace-oci-deploy env=staging tag=main-<shortsha>

# Optional production preview/canary deploy
just dspace-oci-deploy-prod-subdomain tag=main-<shortsha>

# Promote immutable release to production apex
read_prod_tag() { sed -e 's/#.*$//' -e '/^[[:space:]]*$/d' docs/apps/dspace.prod.tag | head -n1 | tr -d '[:space:]'; }
just dspace-oci-promote-prod tag="$(read_prod_tag)"

# Status check
just app-status namespace=dspace release=dspace
```

## Evergreen promotion workflow

Use this loop for each release candidate (`main-<shortsha>`) or release tag (`v<semver>`):

1. Deploy immutable tag to staging:

   ```bash
   just dspace-oci-deploy env=staging tag=main-<shortsha>
   ```

2. Verify staging:

   ```bash
   curl -fsS https://staging.democratized.space/config.json | jq .
   curl -fsS https://staging.democratized.space/healthz | jq .
   curl -fsS https://staging.democratized.space/livez | jq .
   ```

3. Optionally run preview/canary checks:

   ```bash
   just dspace-oci-deploy-prod-subdomain tag=main-<shortsha>
   curl -fsS https://prod.democratized.space/healthz | jq .
   ```

4. Promote same immutable tag to production apex:

   ```bash
   just dspace-oci-promote-prod tag=main-<shortsha>
   ```

5. Roll back by redeploying the previous known-good immutable tag:

   ```bash
   just dspace-oci-promote-prod tag=<previous-main-sha-or-semver-tag>
   ```

## Generic helper examples

```bash
# Install/upgrade with explicit staging overlays
just helm-oci-install \
  release=dspace namespace=dspace \
  chart=oci://ghcr.io/democratizedspace/charts/dspace \
  values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml \
  version_file=docs/apps/dspace.version \
  default_tag=main-latest

# Upgrade staging to an immutable release tag
just helm-oci-upgrade \
  release=dspace namespace=dspace \
  chart=oci://ghcr.io/democratizedspace/charts/dspace \
  values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml \
  version_file=docs/apps/dspace.version \
  tag=main-<shortsha>

# Upgrade production to an immutable release tag
just helm-oci-upgrade \
  release=dspace namespace=dspace \
  chart=oci://ghcr.io/democratizedspace/charts/dspace \
  values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.prod.yaml \
  version_file=docs/apps/dspace.version \
  tag=v<semver>
```

## Networking via Cloudflare Tunnel

Expected public hostnames:

- staging: `https://staging.democratized.space`
- production preview (optional): `https://prod.democratized.space`
- production apex: `https://democratized.space`

For tunnel and DNS setup details, see [Cloudflare Tunnel docs](../cloudflare_tunnel.md).

## Troubleshooting

- Retrieve operator logs by environment:

  ```bash
  just dspace-debug-logs-env env=staging
  just dspace-debug-logs-env env=prod
  ```

- Inspect release state:
  - `helm -n dspace status dspace`
  - `helm -n dspace get values dspace`
  - `kubectl -n dspace get ingress,pods,svc`

- Emergency mutable-tag refresh (non-prod default):

  ```bash
  just dspace-oci-redeploy env=staging
  ```
