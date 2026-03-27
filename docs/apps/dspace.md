# democratized.space (dspace) on Sugarkube

Use the packaged Helm chart from GHCR to install the dspace v3 stack into your cluster.
The `justfile` exposes both:

- generic Helm OCI helpers (`helm-oci-install`, `helm-oci-upgrade`) for any app; and
- a dspace-specific immutable deploy helper (`dspace-oci-deploy`) for RC/stable validation with
  rollout status and post-deploy checks.

Values files are split so you can layer staging-specific ingress settings on top of the default
development values:

- `docs/examples/dspace.values.dev.yaml`: shared defaults for local/dev environments.
- `docs/examples/dspace.values.staging.yaml`: staging-only ingress host and class targeting
  `staging.democratized.space`.
- `docs/examples/dspace.values.prod_preview.yaml`: production-cluster preview ingress host and
  class targeting `prod.democratized.space` before apex cutover.
- `docs/examples/dspace.values.prod.yaml`: production ingress host and class targeting
  `democratized.space`.

The public staging environment for dspace defaults to the `staging.democratized.space`
hostname. You can substitute a different hostname if your Cloudflare Tunnel and DNS are
configured accordingly. For production, this repo supports a two-step rollout:

1. `prod.democratized.space` preview validation (`prod_preview` values).
2. Apex cutover to `democratized.space` (`prod` values).

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

read_prod_tag() { sed -e 's/#.*$//' -e '/^[[:space:]]*$/d' docs/apps/dspace.prod.tag | head -n1 | tr -d '[:space:]'; }

# Immutable-tag production preview deploy (pinned tag from docs/apps/dspace.prod.tag):
just dspace-oci-deploy env=prod-preview tag="$(read_prod_tag)"

# Immutable-tag production apex deploy:
just dspace-oci-deploy env=prod tag="$(read_prod_tag)"

# Check pods and ingress status with the public URL
just app-status namespace=dspace release=dspace

# Generic helper examples (does not wait for rollout):
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
  values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.prod_preview.yaml \
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
  Production deployments should use pinned tags (for example, the value in
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
   just dspace-oci-deploy env=staging tag=v3-<immutable-tag>

   # Production example (pinned tag)
   read_prod_tag() { sed -e 's/#.*$//' -e '/^[[:space:]]*$/d' docs/apps/dspace.prod.tag | head -n1 | tr -d '[:space:]'; }
   just dspace-oci-deploy env=prod tag="$(read_prod_tag)"
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

## v3 production rollout plan (staging → prod preview → apex)

Use this sequence when onboarding dspace v3 to production while keeping staging online.

1. **Provision the prod cluster nodes**: ensure `sugarkube0`, `sugarkube1`, and `sugarkube2`
   are active for production. Keep `sugarkube3` through `sugarkube5` on
   `staging.democratized.space`.
2. **Deploy v3 branch to prod preview host**:
   ```bash
   just kubeconfig-env env=prod
   just dspace-oci-deploy env=prod-preview tag=v3-<immutable-tag>
   ```
3. **Run smoke tests against preview**:
   ```bash
   curl -fsS https://prod.democratized.space/config.json | jq .
   curl -fsS https://prod.democratized.space/healthz | jq .
   curl -fsS https://prod.democratized.space/livez | jq .
   ```
4. **Merge dspace v3 into `main`** in the dspace repository.
5. **Deploy from `main` to prod preview** with a new immutable tag:
   ```bash
   just dspace-oci-deploy env=prod-preview tag=v3-<immutable-main-tag>
   ```
6. **Switch production ingress to apex**:
   ```bash
   just dspace-oci-deploy env=prod tag=v3-<immutable-main-tag>
   ```
7. **Cloudflare cutover**:
   - Keep `democratized.space` pointing to the production Traefik route.
   - Convert `prod.democratized.space` to a simple redirect to `https://democratized.space`.

For emergency mutable-tag refreshes where you need to force pod recycle on `v3-latest`, keep using
`just dspace-oci-redeploy env=staging` (or `env=prod-preview|prod tag=...`).

## Networking via Cloudflare Tunnel

This guide assumes you expose the cluster through a persistent Cloudflare Tunnel. Expected public
hostnames:

- staging: `https://staging.democratized.space`
- prod preview: `https://prod.democratized.space`
- prod apex: `https://democratized.space`

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
