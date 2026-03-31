# democratized.space (dspace) on Sugarkube

Use the packaged Helm chart from GHCR to install the dspace v3 stack into your cluster.
The `justfile` exposes both:

- generic Helm OCI helpers (`helm-oci-install`, `helm-oci-upgrade`) for any app; and
- a dspace-specific immutable deploy helper (`dspace-oci-deploy`) for RC/stable validation with
  rollout status and post-deploy checks.

Values files are split so you can layer environment-specific ingress settings on top of the
default development values:

- `docs/examples/dspace.values.dev.yaml`: shared defaults for local/dev environments.
- `docs/examples/dspace.values.staging.yaml`: staging-only ingress host and class targeting
  `staging.democratized.space`.
- `docs/examples/dspace.values.prod-subdomain.yaml`: **Phase A production-preview** host and class
  targeting `prod.democratized.space` for pre-cutover smoke tests.
- `docs/examples/dspace.values.prod.yaml`: **Phase B production apex** host and class targeting
  `democratized.space`.

Safe two-phase production rollout mapping:

- **Phase A (preview/canary):** `just dspace-oci-deploy-prod-subdomain tag=v3-<immutable-tag>`
  (uses `docs/examples/dspace.values.prod-subdomain.yaml`).
- **Phase B (apex promotion):** `just dspace-oci-promote-prod tag=v3-<immutable-tag>`
  (uses `docs/examples/dspace.values.prod.yaml` via `dspace-oci-deploy env=prod`).

For safety, do not use `docs/examples/dspace.values.prod.yaml` for Phase A preview deploys and
do not manually edit values files to switch hosts.

The public staging environment for dspace defaults to the `staging.democratized.space`
hostname. You can substitute a different hostname if your Cloudflare Tunnel and DNS are
configured accordingly. For production, this repo supports both:

- `prod.democratized.space` (preview/canary endpoint during rollout); and
- `democratized.space` (apex cutover target).

## Prerequisites

- A working k3s cluster with Traefik Ingress available.
- Cloudflare Tunnel client installed on the node that can reach the cluster API.
- A Cloudflare Tunnel route created for the public hostname that will front dspace (defaults to
  `staging.democratized.space`).

## Container image and Helm chart

- Image repository: `ghcr.io/democratizedspace/dspace`
  - Example tag: `ghcr.io/democratizedspace/dspace:v3-latest`
  - Additional tags such as `v3-<short-sha>` or `v<semver>` can be used for specific builds.
- Helm chart: `oci://ghcr.io/democratizedspace/charts/dspace:<chartVersion>`
  - Example: `oci://ghcr.io/democratizedspace/charts/dspace:3.0.0` (chartVersion comes from
    `Chart.yaml`).

Example Sugarkube values snippet targeting the staging environment:

```yaml
images:
  dspace: ghcr.io/democratizedspace/dspace:v3-latest

charts:
  dspace:
    chart: oci://ghcr.io/democratizedspace/charts/dspace:3.0.0
    host: staging.democratized.space
```

## Quickstart

```bash
# Immutable-tag staging deploy (recommended for RC/stable validation):
just dspace-oci-deploy env=staging tag=v3-<immutable-tag>

# Immutable-tag production preview deploy (prod subdomain canary):
just dspace-oci-deploy-prod-subdomain tag=v3-<immutable-tag>

read_prod_tag() { sed -e 's/#.*$//' -e '/^[[:space:]]*$/d' docs/apps/dspace.prod.tag | head -n1 | tr -d '[:space:]'; }

# Immutable-tag production deploy (pinned tag from docs/apps/dspace.prod.tag):
just dspace-oci-deploy env=prod tag="$(read_prod_tag)"

# Alias helper for apex promotion (same effect as the env=prod command above):
just dspace-oci-promote-prod tag="$(read_prod_tag)"

# Check pods and ingress status with the public URL
just app-status namespace=dspace release=dspace

# Generic helper examples (now waits for rollout-managed workloads):
just helm-oci-install \
  release=dspace namespace=dspace \
  chart=oci://ghcr.io/democratizedspace/charts/dspace \
  values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml \
  version_file=docs/apps/dspace.version \
  default_tag=v3-latest

# Bump the image tag with generic Helm helper (optionally override chart version)
just helm-oci-upgrade \
  release=dspace namespace=dspace \
  chart=oci://ghcr.io/democratizedspace/charts/dspace \
  values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml \
  version_file=docs/apps/dspace.version \
  tag=v3-<shortsha>

just helm-oci-upgrade \
  release=dspace namespace=dspace \
  chart=oci://ghcr.io/democratizedspace/charts/dspace \
  values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.prod-subdomain.yaml \
  version_file=docs/apps/dspace.version \
  tag=v3-<immutable-tag>

just helm-oci-upgrade \
  release=dspace namespace=dspace \
  chart=oci://ghcr.io/democratizedspace/charts/dspace \
  values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.prod.yaml \
  version_file=docs/apps/dspace.version \
  tag=v3-<immutable-tag>
```

- `version_file` defaults the Helm chart to the latest tested v3 release stored alongside this
  guide. You can override with `version=<semver>` when pinning a specific chart.
- The image tag defaults to `default_tag` (`v3-latest`) for dev/staging in the generic helpers.
  Production and production-preview deployments should use pinned tags (for example, the value in
  `docs/apps/dspace.prod.tag` or a `v3-<immutable>` build).
- `dspace-oci-deploy` always requires an explicit immutable tag (rejects mutable forms such as
  `latest` and `main`), calls `helm-oci-install` so first-time deploys work, and waits for
  `kubectl rollout status` before returning.

## First deployment walkthrough

Follow this numbered tutorial for a fresh dspace v3 rollout behind Traefik. It
assumes your target cluster (for example `env=staging`) is online and reachable with kubectl.

1. Confirm Traefik is present:

   ```bash
   kubectl -n kube-system get svc -l app.kubernetes.io/name=traefik
   ```

2. Install Cloudflare Tunnel (see [Cloudflare Tunnel docs](../cloudflare_tunnel.md)). Ensure
   `CF_TUNNEL_TOKEN` is exported from the Cloudflare connector snippet, then run:

   ```bash
   just cf-tunnel-install env=staging  # swap env=prod or env=dev as needed
   ```

3. Create a Tunnel route in the Cloudflare dashboard from your FQDN to
   `http://traefik.kube-system.svc.cluster.local:80`. Cluster DNS makes the
   `traefik.kube-system.svc.cluster.local` hostname resolvable from every node,
   so the tunnel can reach Traefik reliably. The default public FQDN for the
   staging environment is `staging.democratized.space`.

4. Install the app:

   ```bash
   # Choose the command that matches your target environment:
   # Staging:
   just dspace-oci-deploy env=staging tag=v3-<immutable-tag>

   # Production preview (Phase A) example using prod.democratized.space:
   just dspace-oci-deploy-prod-subdomain tag=v3-<immutable-tag>

   # Production apex (Phase B) example using democratized.space:
   read_prod_tag() { sed -e 's/#.*$//' -e '/^[[:space:]]*$/d' docs/apps/dspace.prod.tag | head -n1 | tr -d '[:space:]'; }
   just dspace-oci-promote-prod tag="$(read_prod_tag)"
   ```

5. Verify everything is healthy, then browse to the FQDN on your phone or laptop:

   ```bash
   kubectl -n dspace get ingress,pods,svc
   ```

6. Iterate new builds from v3:

   ```bash
   just helm-oci-upgrade \
     release=dspace namespace=dspace \
     chart=oci://ghcr.io/democratizedspace/charts/dspace \
     values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml \
     version_file=docs/apps/dspace.version \
     tag=v3-<shortsha>
   ```

For emergency mutable-tag refreshes where you need to force pod recycle on `v3-latest`, keep using
`just dspace-oci-redeploy env=staging` (or `env=prod tag=...`).

## Production rollout runbook (v3 cutover)

Use this sequence when promoting dspace v3 from staging to production:

1. Deploy the immutable v3 build tag from the `v3` branch to
   `https://prod.democratized.space`:

   ```bash
   just dspace-oci-deploy-prod-subdomain tag=v3-<immutable-tag-from-v3-branch>
   ```

2. Run smoke tests:

   ```bash
   curl -fsS https://prod.democratized.space/config.json | jq .
   curl -fsS https://prod.democratized.space/healthz | jq .
   curl -fsS https://prod.democratized.space/livez | jq .
   ```

3. Merge `v3` into `main`.

4. Deploy the immutable `main` tag to `https://prod.democratized.space`:

   ```bash
   just dspace-oci-deploy-prod-subdomain tag=v3-<immutable-tag-from-main>
   ```

5. Promote to production apex after smoke tests pass:

   ```bash
   just dspace-oci-promote-prod tag=v3-<immutable-tag-from-main>
   ```

6. Update Cloudflare so `prod.democratized.space` becomes a simple redirect to
   `https://democratized.space` once apex is serving v3 successfully.

## Networking via Cloudflare Tunnel

This guide assumes you expose the cluster through a persistent Cloudflare Tunnel. The expected
public hostname is typically `https://staging.democratized.space` (staging),
`https://prod.democratized.space` (production preview), or `https://democratized.space` (apex).

For detailed instructions on creating the Cloudflare Tunnel and DNS records, see:
../cloudflare_tunnel.md

## Troubleshooting

- Retrieve operator logs (staging/prod):
  1. `just dspace-debug-logs-env env=<staging|prod>` first runs `just kubeconfig-env`
     and rewrites `~/.kube/config` to the selected `sugar-<env>` context.
  2. Run the bundled log collector to fetch both app and ingress logs.

  ```bash
  # Staging
  just dspace-debug-logs-env env=staging

  # Production
  just dspace-debug-logs-env env=prod
  ```

  This prints:
  - dspace pod inventory in `namespace=dspace`
  - dspace container logs (`--tail=200` for each dspace pod)
  - Traefik ingress logs in `kube-system` (`--tail=200`)

  If dspace is not in the default namespace, override it on the helper command:

  ```bash
  just dspace-debug-logs-env env=staging namespace=my-dspace-namespace
  ```

  If you already manage `KUBECONFIG` manually, you can run:

  ```bash
  just dspace-debug-logs namespace=dspace
  ```

  Common next steps after the bundled snapshot:

  ```bash
  # Live-tail dspace logs
  kubectl -n dspace logs deploy/dspace --follow

  # Re-check Traefik logs
  kubectl -n kube-system logs -l app.kubernetes.io/name=traefik --tail=200
  ```

- Inspect the release values and history:
  - `helm -n dspace status dspace`
  - `helm -n dspace get values dspace`
- Check the dspace namespace for failing pods or missing ingress resources:
  - `kubectl -n dspace get pods`
  - `kubectl -n dspace describe ingress`
- Validate the Cloudflare Tunnel service and route for the chosen hostname.
- Review cluster-wide logs for Traefik or networking issues if the ingress is not reachable.
