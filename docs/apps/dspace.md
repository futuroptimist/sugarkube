# democratized.space (dspace) on Sugarkube

Use the packaged Helm chart from GHCR to install the dspace v3 stack into your cluster. The
`justfile` exposes generic Helm helpers so you can reuse the same commands for other apps by
changing the arguments.

## Prerequisites

- A working k3s cluster with Traefik Ingress available.
- Cloudflare Tunnel client installed on the node that can reach the cluster API.
- A Cloudflare Tunnel route created for the public hostname that will front dspace.

## Quickstart

```bash
# Install or upgrade the release with a Traefik ingress host (defaults to v3-latest image tag)
just helm:oci-install \
  release=dspace namespace=dspace \
  chart=oci://ghcr.io/democratizedspace/charts/dspace \
  values=docs/examples/dspace.values.dev.yaml \
  version_file=docs/apps/dspace.version \
  host=dspace-v3.<your-domain> \
  default_tag=v3-latest

# Check pods and ingress status with the public URL
just app:status namespace=dspace release=dspace

# Bump the image tag and roll the release (optionally override chart version)
just helm:oci-upgrade \
  release=dspace namespace=dspace \
  chart=oci://ghcr.io/democratizedspace/charts/dspace \
  values=docs/examples/dspace.values.dev.yaml \
  version_file=docs/apps/dspace.version \
  tag=v3-<shortsha>
```

- `version_file` defaults the Helm chart to the latest tested v3 release stored alongside this
  guide. You can override with `version=<semver>` when pinning a specific chart.
- The image tag defaults to `default_tag` (`v3-latest`); pass `tag=<imageTag>` to target a
  specific build.

## Troubleshooting

- Inspect the release values and history:
  - `helm -n dspace status dspace`
  - `helm -n dspace get values dspace`
- Check the dspace namespace for failing pods or missing ingress resources:
  - `kubectl -n dspace get pods`
  - `kubectl -n dspace describe ingress`
- Validate the Cloudflare Tunnel service and route for the chosen hostname.
- Review cluster-wide logs for Traefik or networking issues if the ingress is not reachable.
