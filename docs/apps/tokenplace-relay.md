# token.place relay on Sugarkube

Deploy the `token.place` relay (`relay.py`) to the Sugarkube k3s cluster with a Helm chart that
matches the existing dspace staging patterns. The public staging host is
`staging.token.place`, fronted by Traefik and Cloudflare Tunnel.

Values are split so you can reuse base settings across environments and layer staging-only ingress
overrides:

- `docs/examples/tokenplace-relay.values.dev.yaml`: shared defaults (image repository, annotations).
- `docs/examples/tokenplace-relay.values.staging.yaml`: staging ingress host + TLS secret.

The Helm release runs in the `tokenplace` namespace with release name `tokenplace-relay`.

## Prerequisites

- A working k3s cluster with Traefik installed.
- cert-manager with the `letsencrypt-production` ClusterIssuer ready (DNS01 via Cloudflare).
- Cloudflare Tunnel pointing `staging.token.place` at
  `http://traefik.kube-system.svc.cluster.local:80` (see [Cloudflare Tunnel docs](../cloudflare_tunnel.md)).

## Container image and Helm chart

- Image repository: `ghcr.io/futuroptimist/tokenplace-relay`
  - Tags: `sha-<shortsha>` from `main` pushes, or semver tags when releases are cut.
  - Default staging tag: `sha-19b332e` (current `main` short SHA); override with `tag=<sha-tag>`.
- Helm chart: `./apps/tokenplace-relay`
  - Release: `tokenplace-relay`
  - Namespace: `tokenplace`

Example values snippet:

```yaml
image:
  repository: ghcr.io/futuroptimist/tokenplace-relay
  tag: sha-19b332e
ingress:
  className: traefik
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-production
  host: staging.token.place
  tls:
    secretName: staging-tokenplace-relay-tls
env:
  TOKENPLACE_RELAY_UPSTREAM_URL: http://gpu-server:5015
```

## Quickstart (staging)

```bash
# Install or upgrade the relay with staging ingress + TLS
just helm-oci-install \
  release=tokenplace-relay namespace=tokenplace \
  chart=./apps/tokenplace-relay \
  values=docs/examples/tokenplace-relay.values.dev.yaml,docs/examples/tokenplace-relay.values.staging.yaml \
  default_tag=sha-19b332e

# Print ingress + pod status
just tokenplace-status

# Redeploy a new image tag (sha-<shortsha> from GHCR)
just tokenplace-oci-redeploy tag=sha-<shortsha>
```

- The `default_tag` keeps staging pinned to the latest validated `main` build; pass `tag=sha-<new>`
  when promoting a fresh image.
- Health probes target `/healthz` (readiness) and `/livez` (liveness) on port `5010`.

## Ingress, TLS, and Cloudflare

- Ingress class: `traefik`
- Hostname: `staging.token.place`
- TLS: cert-manager DNS01 via `letsencrypt-production`, secret `staging-tokenplace-relay-tls`
- Cloudflare: create a public hostname that routes `staging.token.place` to
  `http://traefik.kube-system.svc.cluster.local:80` through your staging tunnel, mirroring the
  dspace setup in [cloudflare_tunnel.md](../cloudflare_tunnel.md).

## Operational helpers

- Check status: `just tokenplace-status` (prints pods/ingress and the public URL)
- Tail logs: `just tokenplace-logs`
- Port-forward locally: `just tokenplace-port-forward` then `curl http://127.0.0.1:5010/healthz`

## Troubleshooting

- Inspect the release: `helm -n tokenplace status tokenplace-relay`
- Verify ingress + certificate:
  - `kubectl -n tokenplace get ingress`
  - `kubectl -n tokenplace describe certificate staging-tokenplace-relay-tls`
- Check relay health directly:
  - `just tokenplace-port-forward`
  - `curl -fsS http://127.0.0.1:5010/healthz`
- Logs:
  - `just tokenplace-logs`
- Cloudflare Tunnel:
  - Confirm the tunnel routes `staging.token.place` to Traefik (`http://traefik.kube-system.svc.cluster.local:80`)
  - Validate DNS for `staging.token.place` in Cloudflare.
