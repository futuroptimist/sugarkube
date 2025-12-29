# token.place relay (staging) on Sugarkube

Deploy the token.place relay to the Sugarkube k3s cluster with the bundled Helm chart and
`just` recipes. The release mirrors the dspace ergonomics: Traefik ingress, cert-manager
TLS, and single-command redeploys against GHCR images.

Key settings:

- Release: `tokenplace-relay`
- Namespace: `tokenplace`
- Chart: `apps/tokenplace-relay`
- Values: `docs/examples/tokenplace-relay.values.staging.yaml`
- Ingress host: `staging.token.place`
- TLS secret: `staging-token-place-tls`
- Ingress class: `traefik`
- cert-manager issuer: `letsencrypt-production`

## Container image

- Repository: `ghcr.io/futuroptimist/tokenplace-relay`
- Tags: immutable `sha-<shortsha>` on every `main` commit plus semver tags on releases
- Default staging tag: `sha-19b332e` (latest `main` build at time of writing)

## Quickstart

1) Install or upgrade the release (creates the namespace if missing):

```bash
just tokenplace-oci-redeploy
```

Pass a specific tag to target a different GHCR build (for example, a semver tag or a newer
`sha-*`):

```bash
just tokenplace-oci-redeploy tag=sha-<shortsha>
```

2) Check status and the public URL recorded in the release values:

```bash
just tokenplace-status
```

3) Tail logs for troubleshooting:

```bash
just tokenplace-logs
```

The staging values layer Traefik ingress, the TLS secret name, and `TOKEN_PLACE_ENV=staging`.
The chart exposes `/livez` and `/healthz` probes on port `5010` and publishes them through the
`tokenplace-relay` Service on port `80`.

Set `env.TOKENPLACE_RELAY_UPSTREAM_URL` in the staging values file to match the GPU host that serves
the relay backend. The default points at `http://gpu-server:3000`, which aligns with the upstream
defaults in the token.place repository.

## Ingress, TLS, and Cloudflare

The relay uses the same ingress pattern as dspace staging: Traefik handles routing and
cert-manager issues certificates via Cloudflare DNS-01.

- Ingress host: `staging.token.place`
- Ingress class: `traefik`
- TLS secret: `staging-token-place-tls`
- Annotation: `cert-manager.io/cluster-issuer: letsencrypt-production`

Follow the Cloudflare Tunnel guide to expose the host through your tunnel:

1. Deploy `cloudflared` per [cloudflare_tunnel.md](../cloudflare_tunnel.md) so the cluster joins
   your tunnel.
2. In the Cloudflare dashboard, add a **Public Hostname** that maps
   `staging.token.place` → `http://traefik.kube-system.svc.cluster.local:80`.
3. Ensure Cloudflare DNS has a proxied CNAME for `staging.token.place` pointing at the tunnel’s
   `*.cfargotunnel.com` target (the dashboard usually creates this automatically).

## Redeploy from GHCR

`just tokenplace-oci-redeploy` shells out to `helm upgrade --install` with the staging values file
and defaults the image tag to `sha-19b332e`. Override the tag to roll a specific build:

```bash
just tokenplace-oci-redeploy tag=sha-abcd1234
```

The helper sets `--set ingress.host=staging.token.place` to avoid collisions with other releases
and restarts the deployment once Helm finishes.

## Troubleshooting

- Check release values and ingress:
  - `helm -n tokenplace status tokenplace-relay`
  - `kubectl -n tokenplace get ingress,pods,svc`
- Verify TLS issuance:
  - `kubectl -n tokenplace describe certificate staging-token-place-tls`
  - `kubectl -n cert-manager logs deploy/cert-manager --tail=200`
- Confirm Cloudflare routing matches the Traefik service target in the Tunnel UI.
- Inspect pod logs for relay errors:
  - `just tokenplace-logs`
- Probe health endpoints (port-forward if needed):
  - `kubectl -n tokenplace port-forward deploy/tokenplace-relay 5010:5010`
  - `curl -fsS http://localhost:5010/healthz`

If ingress returns 404s, double-check the Cloudflare hostname, the Traefik ingress class, and the
TLS secret name. When cert-manager cannot issue a certificate, inspect the `Order`/`Challenge`
status in the cert-manager namespace and ensure the Cloudflare API token secret is present.
