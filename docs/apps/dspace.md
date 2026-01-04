# democratized.space (dspace) on Sugarkube

Use the packaged Helm chart from GHCR to install the dspace v3 stack into your cluster. The
`justfile` exposes generic Helm helpers so you can reuse the same commands for other apps by
changing the arguments.

Values files are split so you can layer staging-specific ingress settings on top of the default
development values:

- `docs/examples/dspace.values.dev.yaml`: shared defaults for local/dev environments.
- `docs/examples/dspace.values.staging.yaml`: staging-only ingress host and class targeting
  `staging.democratized.space`.
- `docs/examples/dspace.values.prod.yaml`: production ingress host and class targeting
  `democratized.space`.

The public staging environment for dspace defaults to the `staging.democratized.space`
hostname. You can substitute a different hostname if your Cloudflare Tunnel and DNS are
configured accordingly. For production, use the prod values file and your production hostname
(defaults to `democratized.space` in this repo).

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
# Install or upgrade the release with staging ingress overrides (defaults to v3-latest image tag)
just helm-oci-install \
  release=dspace namespace=dspace \
  chart=oci://ghcr.io/democratizedspace/charts/dspace \
  values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml \
  version_file=docs/apps/dspace.version \
  default_tag=v3-latest

# Install production with prod ingress overrides and a pinned tag
just helm-oci-install \
  release=dspace namespace=dspace \
  chart=oci://ghcr.io/democratizedspace/charts/dspace \
  values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.prod.yaml \
  version_file=docs/apps/dspace.version \
  tag=$(cat docs/apps/dspace.prod.tag)

# Check pods and ingress status with the public URL
just app-status namespace=dspace release=dspace

# Bump the image tag and roll the release (optionally override chart version)
just helm-oci-upgrade \
  release=dspace namespace=dspace \
  chart=oci://ghcr.io/democratizedspace/charts/dspace \
  values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml \
  version_file=docs/apps/dspace.version \
  tag=v3-<shortsha>

just helm-oci-upgrade \
  release=dspace namespace=dspace \
  chart=oci://ghcr.io/democratizedspace/charts/dspace \
  values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.prod.yaml \
  version_file=docs/apps/dspace.version \
  tag=v3-<immutable-tag>
```

- `version_file` defaults the Helm chart to the latest tested v3 release stored alongside this
  guide. You can override with `version=<semver>` when pinning a specific chart.
- The image tag defaults to `default_tag` (`v3-latest`) for dev/staging; pass `tag=<imageTag>` to
  target a specific build. Production deployments should use pinned tags (for example, the value in
  `docs/apps/dspace.prod.tag` or a `v3-<immutable>` build).

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
   just helm-oci-install \
     release=dspace namespace=dspace \
     chart=oci://ghcr.io/democratizedspace/charts/dspace \
     values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml \
     version_file=docs/apps/dspace.version \
     default_tag=v3-latest

   # Production example (pinned tag)
   just helm-oci-install \
     release=dspace namespace=dspace \
     chart=oci://ghcr.io/democratizedspace/charts/dspace \
     values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.prod.yaml \
     version_file=docs/apps/dspace.version \
     tag=$(cat docs/apps/dspace.prod.tag)
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

## Networking via Cloudflare Tunnel

This guide assumes you expose the cluster through a persistent Cloudflare Tunnel. The expected
public hostname is `https://staging.democratized.space`.

For detailed instructions on creating the Cloudflare Tunnel and DNS records, see:
../cloudflare_tunnel.md

## Troubleshooting

- Inspect the release values and history:
  - `helm -n dspace status dspace`
  - `helm -n dspace get values dspace`
- Check the dspace namespace for failing pods or missing ingress resources:
  - `kubectl -n dspace get pods`
  - `kubectl -n dspace describe ingress`
- Validate the Cloudflare Tunnel service and route for the chosen hostname.
- Review cluster-wide logs for Traefik or networking issues if the ingress is not reachable.
