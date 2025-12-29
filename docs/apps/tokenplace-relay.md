# token.place relay on Sugarkube

Run the token.place relay behind Traefik in the `tokenplace` namespace with a Helm chart that
follows the same Sugarkube patterns used for dspace. The relay proxies browser traffic to the GPU
host running `server.py` while exposing health and metrics endpoints for debugging.

Values files mirror the dspace split between shared defaults and staging-only overrides:

- `docs/examples/tokenplace-relay.values.dev.yaml`: defaults for Traefik, resources, and upstream.
- `docs/examples/tokenplace-relay.values.staging.yaml`: staging ingress host, TLS secret, image tag,
  and secret references.

The staging hostname is `staging.token.place`. Update the overlay if the Cloudflare DNS record uses a
different FQDN.

## Prerequisites

- Traefik Ingress running in the cluster.
- cert-manager with the `letsencrypt-production` ClusterIssuer ready for DNS-01 (Cloudflare) solves.
- A Cloudflare Tunnel that routes `staging.token.place` to
  `http://traefik.kube-system.svc.cluster.local:80`.
- A Kubernetes Secret containing `TOKEN_PLACE_RELAY_SERVER_TOKEN` when relay server registration
  should be enforced (referenced by default as `tokenplace-relay-secrets`).

## Container image and chart

- Image: `ghcr.io/futuroptimist/tokenplace-relay`.
  - Tags follow the GitHub Actions workflow: `sha-<shortsha>` on every push, optional semver tags.
  - Default staging tag: `sha-19b332e` (latest main at the time of writing). Override with
    `tag=sha-<shortsha>` to target a specific build.
- Chart: local path `apps/tokenplace-relay` (packaged from this repository).
- Release: `tokenplace-relay` in namespace `tokenplace`.
- Ingress: Traefik class, host `staging.token.place`, TLS secret `staging-token-place-tls` issued by
  `letsencrypt-production`.
- Service: ClusterIP on port 80 forwarding to container port 5010.
- Probes: readiness `/healthz`, liveness `/livez`, both on the named `http` port.

## Quickstart (staging)

```bash
# Deploy or upgrade the relay with staging overrides
just tokenplace-oci-redeploy

# Show pods and ingress along with the public URL from Helm values
just tokenplace-status

# Tail relay and Traefik logs if routing fails
just tokenplace-logs
```

Pass `tag=sha-<shortsha>` to `tokenplace-oci-redeploy` when pinning a different image:

```bash
just tokenplace-oci-redeploy tag=sha-deadbee
```

## Ingress, TLS, and Cloudflare DNS

- Set the Cloudflare **Public hostname** route to `staging.token.place` →
  `http://traefik.kube-system.svc.cluster.local:80`.
- `docs/examples/tokenplace-relay.values.staging.yaml` requests a cert-manager certificate via
  `cert-manager.io/cluster-issuer: letsencrypt-production` and stores it in
  `staging-token-place-tls`.
- Keep the host in both the ingress rule and TLS section so cert-manager associates the certificate
  with the correct FQDN.
- Follow [cloudflare_tunnel.md](../cloudflare_tunnel.md) for detailed tunnel creation steps. Mirror
  the same procedure used for dspace staging, substituting the token.place hostname and secret.

## Configuration and secrets

Environment variables are driven from the chart values:

- `RELAY_HOST` / `RELAY_PORT`: bind the service (default `0.0.0.0:5010`).
- `TOKENPLACE_RELAY_UPSTREAM_URL`: GPU target URL (defaults to `http://gpu-server:3000`).
- Optional `TOKENPLACE_GPU_HOST` / `TOKENPLACE_GPU_PORT` for explicit GPU host mapping.
- Optional `TOKEN_PLACE_RELAY_SERVER_TOKEN` from the `tokenplace-relay-secrets` Secret to require
  compute nodes to present `X-Relay-Server-Token`.

Secrets stay out of git: create `tokenplace-relay-secrets` in the `tokenplace` namespace with the
registration token key before deploying, or drop `envFromSecrets` if you do not need server
registration.

## Troubleshooting

- Ingress and certificate:
  - `kubectl -n tokenplace get ingress,pods,svc`
  - `kubectl -n tokenplace describe ingress tokenplace-relay`
  - `kubectl -n tokenplace get certificate`
- Relay logs: `just tokenplace-logs` (includes Traefik for routing context).
- Health endpoints:
  - `curl -fsS https://staging.token.place/healthz`
  - `curl -fsS https://staging.token.place/livez`
- kubectl port-forward for local testing: `just tokenplace-port-forward local_port=8500` then
  `curl -fsS http://localhost:8500/healthz`.
- Verify the Cloudflare Tunnel route in the dashboard matches `staging.token.place` and points to the
  Traefik service DNS name.
