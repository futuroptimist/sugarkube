# democratized.space (dspace) on Sugarkube

Use the packaged Helm chart from GHCR to run dspace across Sugarkube environments.
This guide is for **steady-state operations**: repeated deploys, promotions, and rollbacks.

The `justfile` exposes both:

- generic Helm OCI helpers (`helm-oci-install`, `helm-oci-upgrade`) for any app; and
- dspace-specific wrappers (`dspace-oci-deploy`, `dspace-oci-promote-prod`,
  `dspace-oci-redeploy`) that encode safer defaults for immutable-tag rollouts.

## Environment topology

Current and planned dspace topology:

- **staging (live, HA):** `staging.democratized.space` on `sugarkube3`, `sugarkube4`, `sugarkube5`
  with `env=staging`.
- **prod (live, HA):** `democratized.space` on `sugarkube0`, `sugarkube1`, `sugarkube2` with
  `env=prod`.
- **dev (planned):** future non-HA single-node deployment on `sugarkube6` with `env=dev`.

Values files are layered by environment:

- `docs/examples/dspace.values.dev.yaml`: shared baseline and the future `env=dev` base values.
- `docs/examples/dspace.values.staging.yaml`: staging ingress host/class.
- `docs/examples/dspace.values.prod.yaml`: production apex ingress host/class (`democratized.space`).
- `docs/examples/dspace.values.prod-subdomain.yaml`: optional production preview/canary host
  (`prod.democratized.space`).

## Tags and release hygiene

- `main-latest`: convenience tag for rapid non-prod refreshes.
- `main-<shortsha>`: immutable commit-derived tag for RC validation.
- `v<semver>` (for example `v3.1.0`): immutable release tag suitable for sign-off and rollback.

Prefer immutable tags for staging sign-off and all production deploys. Mutable tags are convenient
for development, but they are weaker for auditability and rollback precision.

## Container image and Helm chart

- Image repository: `ghcr.io/democratizedspace/dspace`
  - Examples: `ghcr.io/democratizedspace/dspace:main-latest`,
    `ghcr.io/democratizedspace/dspace:main-<shortsha>`,
    `ghcr.io/democratizedspace/dspace:v3.1.0`
- Helm chart: `oci://ghcr.io/democratizedspace/charts/dspace:<chartVersion>`
  - Example: `oci://ghcr.io/democratizedspace/charts/dspace:3.0.0`

Example values snippet targeting staging:

```yaml
images:
  dspace: ghcr.io/democratizedspace/dspace:main-latest

charts:
  dspace:
    chart: oci://ghcr.io/democratizedspace/charts/dspace:3.0.0
    host: staging.democratized.space
```

## Quickstart commands

```bash
# Immutable staging deploy (recommended for sign-off):
just dspace-oci-deploy env=staging tag=main-<immutable-tag>

# Optional immutable production preview deploy (prod subdomain canary):
just dspace-oci-deploy-prod-subdomain tag=main-<immutable-tag>

read_prod_tag() { sed -e 's/#.*$//' -e '/^[[:space:]]*$/d' docs/apps/dspace.prod.tag | head -n1 | tr -d '[:space:]'; }

# Immutable production apex deploy (pinned tag file):
just dspace-oci-deploy env=prod tag="$(read_prod_tag)"

# Alias helper for apex promotion (same effect as command above):
just dspace-oci-promote-prod tag="$(read_prod_tag)"

# Check pods and ingress status:
just app-status namespace=dspace release=dspace
```

### Generic helper examples (when you need direct Helm control)

Use `helm-oci-install` for first install / install-if-missing behavior.
Use `helm-oci-upgrade` for upgrade-only operations that should fail if not installed.

```bash
# Install (or upgrade with --install) against staging overlay
just helm-oci-install \
  release=dspace namespace=dspace \
  chart=oci://ghcr.io/democratizedspace/charts/dspace \
  values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml \
  version_file=docs/apps/dspace.version \
  default_tag=main-latest

# Upgrade with an immutable staging candidate tag
just helm-oci-upgrade \
  release=dspace namespace=dspace \
  chart=oci://ghcr.io/democratizedspace/charts/dspace \
  values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml \
  version_file=docs/apps/dspace.version \
  tag=main-<shortsha>

# Optional preview-subdomain canary upgrade
just helm-oci-upgrade \
  release=dspace namespace=dspace \
  chart=oci://ghcr.io/democratizedspace/charts/dspace \
  values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.prod-subdomain.yaml \
  version_file=docs/apps/dspace.version \
  tag=v<semver>

# Production apex upgrade
just helm-oci-upgrade \
  release=dspace namespace=dspace \
  chart=oci://ghcr.io/democratizedspace/charts/dspace \
  values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.prod.yaml \
  version_file=docs/apps/dspace.version \
  tag=v<semver>
```

Notes:

- `dspace-oci-deploy` always requires an explicit immutable tag and rejects mutable forms.
- `dspace-oci-deploy` uses `helm-oci-install` internally so first-time deploys work.
- `docs/apps/dspace.version` pins the default tested chart version.
- `docs/apps/dspace.prod.tag` is the pinned default immutable image tag for production deploys.

## Evergreen promotion workflow

Use this for each release cycle (for example `v3.0.1`, `v3.1.0`, `v3.1.1`):

1. Deploy immutable candidate to staging:

   ```bash
   just dspace-oci-deploy env=staging tag=main-<shortsha>
   ```

2. Run staging smoke tests:

   ```bash
   curl -fsS https://staging.democratized.space/config.json | jq .
   curl -fsS https://staging.democratized.space/healthz | jq .
   curl -fsS https://staging.democratized.space/livez | jq .
   ```

3. Choose production immutable tag (`main-<shortsha>` or `v<semver>`) and pin it:

   ```bash
   printf '%s\n' 'v3.1.0' > docs/apps/dspace.prod.tag
   ```

4. Optional preview-subdomain canary before apex:

   ```bash
   just dspace-oci-deploy-prod-subdomain tag="$(read_prod_tag)"
   ```

5. Promote to production apex:

   ```bash
   just dspace-oci-promote-prod tag="$(read_prod_tag)"
   ```

6. Verify production:

   ```bash
   curl -fsS https://democratized.space/config.json | jq .
   curl -fsS https://democratized.space/healthz | jq .
   curl -fsS https://democratized.space/livez | jq .
   ```

## Emergency redeploy (mutable refresh)

For emergency refreshes where you intentionally want the newest digest behind `main-latest`:

```bash
# Non-prod convenience flow
just dspace-oci-redeploy env=staging

# Production always requires an immutable tag (or docs/apps/dspace.prod.tag)
just dspace-oci-redeploy env=prod tag=v3.1.0
```

## Networking via Cloudflare Tunnel

This guide assumes dspace is exposed through Cloudflare Tunnel. Common hostnames:

- staging: `https://staging.democratized.space`
- optional production preview: `https://prod.democratized.space`
- production apex: `https://democratized.space`

For tunnel setup details, see `../cloudflare_tunnel.md`.

## Troubleshooting

- Retrieve operator logs:

  ```bash
  just dspace-debug-logs-env env=staging
  just dspace-debug-logs-env env=prod
  ```

- If namespace differs, override it:

  ```bash
  just dspace-debug-logs-env env=staging namespace=my-dspace-namespace
  ```

- If managing kubeconfig manually:

  ```bash
  just dspace-debug-logs namespace=dspace
  ```

- Additional checks:
  - `helm -n dspace status dspace`
  - `helm -n dspace get values dspace`
  - `kubectl -n dspace get pods,svc,ingress`
  - `kubectl -n kube-system logs -l app.kubernetes.io/name=traefik --tail=200`
