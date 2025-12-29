# token.place relay on Sugarkube

Deploy the `token.place` relay (`relay.py`) to the Sugarkube k3s cluster with a Helm chart that
matches the existing dspace staging patterns. The public staging host for the relay service is
`staging.token.place`, fronted by Traefik and Cloudflare Tunnel.

Values are split so you can reuse base settings across environments and layer staging-only ingress
overrides. Operator defaults live alongside the chart; the docs copies remain as examples for
cut-and-paste use:

- `apps/tokenplace-relay/values.dev.yaml`: shared defaults (image repository, annotations).
- `apps/tokenplace-relay/values.staging.yaml`: staging ingress host + TLS secret.
- `docs/examples/tokenplace-relay.values.*.yaml`: example mirrors of the operator defaults.

The Helm release runs in the `tokenplace` namespace with release name `tokenplace-relay`.

## Prerequisites

- A working k3s cluster with Traefik installed.
- cert-manager with the `letsencrypt-production` ClusterIssuer ready (DNS01 via Cloudflare).
- Cloudflare Tunnel pointing `staging.token.place` at
  `http://traefik.kube-system.svc.cluster.local:80` (see [Cloudflare Tunnel docs](../cloudflare_tunnel.md)).

## Container image and Helm chart

- Image repository: `ghcr.io/democratizedspace/tokenplace-relay`
  - Tags: `main` (latest build) or immutable `sha-<shortsha>` builds from the CI publisher.
  - Default staging tag: `main` (set via `default_tag` in the helper); prefer `tag=sha-<sha>` for promoted releases.
- Helm chart: `./apps/tokenplace-relay`
  - Release: `tokenplace-relay`
  - Namespace: `tokenplace`

Example values snippet:

```yaml
image:
  repository: ghcr.io/democratizedspace/tokenplace-relay
  tag: main
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
just tokenplace-oci-redeploy tag=main

# Print ingress + pod status
just tokenplace-status

# Redeploy a new image tag (sha-<shortsha> from GHCR) after validating a build
just tokenplace-oci-redeploy tag=sha-<shortsha>
```

- The `default_tag` keeps staging pinned to the latest validated `main` build; pass `tag=sha-<new>`
  when promoting a fresh image.
- Health probes default to `/healthz` (readiness) and `/livez` (liveness) on the `http` port
  (`containerPort: 5010`). Override `probes.port`, `probes.readiness.path`, or `probes.liveness.path`
  if the relay exposes a different endpoint.
- Expected public URL: https://staging.token.place
- Manual Helm install uses the operator values:

  ```bash
  helm upgrade --install tokenplace-relay ./apps/tokenplace-relay \
    --namespace tokenplace --create-namespace \
    -f apps/tokenplace-relay/values.dev.yaml \
    -f apps/tokenplace-relay/values.staging.yaml
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

- Deploy or roll forward: `just tokenplace-oci-redeploy tag=<main|sha-...>` (release `tokenplace-relay`
  in namespace `tokenplace`, values from `apps/tokenplace-relay/values.*.yaml`)
- Check status: `just tokenplace-status` (prints pods/ingress and the public URL)
- Tail logs: `just tokenplace-logs`
- Port-forward locally: `just tokenplace-port-forward` then `curl http://127.0.0.1:5010/healthz`

## Troubleshooting

- Inspect the release: `helm -n tokenplace status tokenplace-relay`
- Verify ingress + certificate:
  - `kubectl -n tokenplace get ingress`
  - `kubectl -n tokenplace describe ingress tokenplace-relay`
  - `kubectl -n tokenplace describe certificate staging-tokenplace-relay-tls`
- Check relay health directly:
  - `just tokenplace-port-forward`
  - `curl -fsS http://127.0.0.1:5010/healthz`
- Logs:
  - `just tokenplace-logs`
- Cloudflare Tunnel:
  - Confirm the tunnel routes `staging.token.place` to Traefik (`http://traefik.kube-system.svc.cluster.local:80`)
  - Validate DNS for `staging.token.place` in Cloudflare.
