# token.place relay on Sugarkube

Deploy the `token.place` relay (`relay.py`) to the Sugarkube k3s cluster with a Helm chart that
matches the existing dspace staging patterns. The public staging host for the relay service is
`staging.token.place`, fronted by Traefik and Cloudflare Tunnel.

For full token.place onboarding and environment runbooks, see
[`docs/tokenplace_sugarkube_onboarding.md`](../tokenplace_sugarkube_onboarding.md) and [`docs/apps/tokenplace.md`](./tokenplace.md).

Values are split so you can reuse base settings across environments and layer staging-only ingress
overrides. Operator defaults now live in the docs-owned canonical files:

- `docs/examples/tokenplace.values.dev.yaml`: shared defaults (image repository, ingress baseline, shared env).
- `docs/examples/tokenplace.values.staging.yaml`: staging ingress host + TLS secret.
- `docs/examples/tokenplace.values.prod.yaml`: production ingress host + TLS secret.
- `docs/apps/tokenplace.version`: pinned chart version for deploy wrappers.

The Helm release runs in the `tokenplace` namespace with release name `tokenplace`.

## Prerequisites

- A working k3s cluster with Traefik installed.
- cert-manager with the `letsencrypt-production` ClusterIssuer ready (DNS01 via Cloudflare).
- Cloudflare Tunnel pointing `staging.token.place` at
  `http://traefik.kube-system.svc.cluster.local:80` (see [Cloudflare Tunnel docs](../cloudflare_tunnel.md)).

## Container image and Helm chart

- Image repository: `ghcr.io/futuroptimist/tokenplace-relay`
  - Tags: immutable `sha-<shortsha>` builds from the CI publisher (recommended) and `main` (mutable).
  - Default staging tag: `sha-684fd7f` (set via `default_tag` in the helper); override with `tag=sha-<shortsha>` for promotions.
- Helm chart: `oci://ghcr.io/futuroptimist/charts/tokenplace`
  - Release: `tokenplace`
  - Namespace: `tokenplace`

Example values snippet:

```yaml
image:
  repository: ghcr.io/futuroptimist/tokenplace-relay
  tag: sha-684fd7f
ingress:
  className: traefik
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-production
  host: staging.token.place
  tls:
    secretName: staging-tokenplace-relay-tls
env:
  TOKENPLACE_RELAY_UPSTREAM_URL: http://gpu-server:5015
probes:
  port: http
  readiness:
    path: /healthz
  liveness:
    path: /livez
```

## Quickstart (staging)

```bash
# Install or upgrade the relay with staging ingress + TLS (wraps helm upgrade --install)
just tokenplace-oci-redeploy

# Print ingress + pod status
just tokenplace-status

# Redeploy a new image tag (sha-<shortsha> from GHCR) after validating a build
just tokenplace-oci-redeploy tag=sha-<shortsha>
```

- The `default_tag` keeps staging pinned to a vetted immutable SHA tag; pass `tag=sha-<shortsha>`
  when promoting a fresh image.
- Health probes default to `/healthz` (readiness) and `/livez` (liveness) on the `http` port
  (`containerPort: 5010`). Override `probes.port`, `probes.readiness.path`, or `probes.liveness.path`
  if the relay exposes a different endpoint.
- Expected public URL: https://staging.token.place
- Manual Helm install uses the operator values:

  ```bash
  helm upgrade --install tokenplace oci://ghcr.io/futuroptimist/charts/tokenplace \
    --namespace tokenplace --create-namespace \
    -f docs/examples/tokenplace.values.dev.yaml \
    -f docs/examples/tokenplace.values.staging.yaml \
    --version "$(cat docs/apps/tokenplace.version)"
  ```

## Ingress, TLS, and Cloudflare

- Ingress class: `traefik`
- Hostname: `staging.token.place`
- TLS: cert-manager DNS01 via `letsencrypt-production`, secret `staging-tokenplace-relay-tls`
- Cloudflare DNS:
  1. Ensure your tunnel routes `staging.token.place` to
     `http://traefik.kube-system.svc.cluster.local:80` (see [cloudflare_tunnel.md](../cloudflare_tunnel.md)).
  2. In Cloudflare DNS, create a proxied CNAME for `staging.token.place` pointing at the
     tunnel’s `<UUID>.cfargotunnel.com` target. Leave Proxy enabled so TLS terminates at Cloudflare
     before entering Traefik.
- TLS troubleshooting:
  - `kubectl -n tokenplace describe certificate staging-tokenplace-relay-tls`
  - `kubectl -n tokenplace describe challenge` (if certificates stall)
  - `kubectl -n cert-manager logs deploy/cert-manager`
  - `kubectl -n kube-system logs -l app.kubernetes.io/name=traefik`

## Operational helpers

- Deploy or roll forward: `just tokenplace-oci-redeploy [tag=sha-...]` (release `tokenplace`
  in namespace `tokenplace`, values from `docs/examples/tokenplace.values.*.yaml`)
- Check status: `just tokenplace-status` (prints pods/ingress and the public URL)
- Tail logs: `just tokenplace-logs`
- Port-forward locally: `just tokenplace-port-forward` then `curl http://127.0.0.1:5010/healthz`

## Troubleshooting

- Inspect the release: `helm -n tokenplace status tokenplace`
- Verify ingress + certificate:
  - `kubectl -n tokenplace get ingress`
  - `kubectl -n tokenplace describe ingress tokenplace`
  - `kubectl -n tokenplace describe certificate staging-tokenplace-relay-tls`
- Check relay health directly:
  - `just tokenplace-port-forward`
  - `curl -fsS http://127.0.0.1:5010/healthz`
- Logs:
  - `just tokenplace-logs`
- Cloudflare Tunnel:
  - Confirm the tunnel routes `staging.token.place` to Traefik (`http://traefik.kube-system.svc.cluster.local:80`)
  - Validate DNS for `staging.token.place` in Cloudflare.
