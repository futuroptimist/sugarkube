# token.place relay on Sugarkube

Deploy the token.place relay (`relay.py`) to the Sugarkube k3s cluster with Helm. This chart mirrors
the dspace staging workflow: Traefik ingress, cert-manager certificates, and `just` helpers for
routine operations.

## Prerequisites

- k3s cluster with Traefik installed (`kube-system` namespace).
- cert-manager configured with the `letsencrypt-production` ClusterIssuer.
- Cloudflare Tunnel routing `staging.token.place` → `http://traefik.kube-system.svc.cluster.local:80`
  (see [Cloudflare Tunnel](../cloudflare_tunnel.md)).

## Container image and chart

- Image: `ghcr.io/futuroptimist/tokenplace-relay`
  - CI publishes `sha-<shortsha>` tags from the `futuroptimist/token.place` repository.
  - Default staging tag in this repo: `sha-19b332e` (override with `tag=sha-<shortsha>` when
    redeploying).
- Helm chart: local chart at `apps/tokenplace-relay`
  - Release: `tokenplace-relay`
  - Namespace: `tokenplace`

## Quickstart (staging)

```bash
# Install/upgrade the relay with staging overrides (host, TLS, network policy)
just tokenplace-oci-redeploy            # optionally pass tag=sha-<shortsha>

# Inspect pods and ingress
just tokenplace-status
```

- The release renders ingress for `https://staging.token.place` with TLS secret
  `staging-token-place-tls` and Traefik class `traefik`.
- Pods expose readiness (`/healthz`) and liveness (`/livez`) probes on port 5010 and request
  `100m/256Mi` with limits `500m/512Mi`.
- NetworkPolicy defaults to DNS-only egress; set `gpuExternalName.headless.addresses` or
  `networkPolicy.externalNameCIDR` when the relay must reach upstream `server.py` hosts.

## Ingress, TLS, and Cloudflare

- Ingress host: `staging.token.place`
- TLS: `cert-manager.io/cluster-issuer: letsencrypt-production`, secret `staging-token-place-tls`.
- Cloudflare: create (or reuse) a tunnel route that maps the host to
  `http://traefik.kube-system.svc.cluster.local:80` exactly as documented for dspace in
  [cloudflare_tunnel.md](../cloudflare_tunnel.md). Ensure DNS points the hostname at the tunnel’s
  `*.cfargotunnel.com` address (proxied CNAME).

## Operations

- Redeploy: `just tokenplace-oci-redeploy tag=sha-<shortsha>`
- Status: `just tokenplace-status`
- Logs: `just tokenplace-logs` (tails the last 200 lines from relay pods)

## Troubleshooting

- Ingress/TLS: `kubectl -n tokenplace get ingress` and `kubectl -n tokenplace describe ingress` to
  confirm the host and certificate status.
- cert-manager: `kubectl -n tokenplace get certificate,order,challenge` when issuance is stuck.
- Pods: `just tokenplace-logs` for relay output; `kubectl -n tokenplace get pods -o wide` for node
  placement and restarts.
- Health endpoints: `kubectl -n tokenplace port-forward deploy/tokenplace-relay 5010:5010` then
  `curl -fsS http://localhost:5010/healthz` and `curl -fsS http://localhost:5010/livez`.
