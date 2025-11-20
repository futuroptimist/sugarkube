# Cloudflare Tunnel (cloudflared) via Helm

This guide installs the official [`cloudflare/cloudflare-tunnel`](https://cloudflare.github.io/helm-charts)
Helm chart using the **tunnel token** flow (remote-managed configuration) and publishes a hostname to
the cluster's Traefik ingress.

## Prerequisites
- A Cloudflare zone with access to **Cloudflare Tunnel**.
- A remote-managed Tunnel created in the Cloudflare dashboard.
- The tunnel token from that Tunnel (copy from **Connect a site** → **Cloudflare Tunnel** → select
  your Tunnel → **Manage** → **Token**).
- `helm` and `kubectl` available against the target cluster.

## Install the Tunnel
1. Export the tunnel token (or pass `token=` inline):
   ```bash
   export CF_TUNNEL_TOKEN="<tunnel-token>"
   export CF_TUNNEL_NAME="<dashboard-tunnel-name>"   # Optional: overrides sugarkube-<env>
   export CF_TUNNEL_ID="<dashboard-tunnel-id>"        # Optional: helps keep names aligned
   ```
2. Install/update the chart and Secret (creates the namespace if needed):
   ```bash
   just cf-tunnel-install env=dev token="$CF_TUNNEL_TOKEN"
   ```
3. Verify readiness (Pods should report `/ready` = `200`):
   ```bash
   kubectl -n cloudflare get deploy,po -l app.kubernetes.io/name=cloudflare-tunnel
   kubectl -n cloudflare exec deploy/cloudflare-tunnel -- curl -fsS http://localhost:2000/ready
   ```

## Route a hostname to Traefik
1. Discover the Traefik Service (for reference and health checks):
   ```bash
   kubectl -n kube-system get svc -l app.kubernetes.io/name=traefik
   ```
2. Determine the Service FQDN that Cloudflare should target (HTTP on port 80):
   ```bash
   just cf-tunnel-route host=dspace-v3.example.com
   # Service URL: http://traefik.kube-system.svc.cluster.local:80
   ```
3. In the Cloudflare dashboard, add an **Application** (or **Public hostname**) entry under your
   Tunnel that maps your chosen hostname (e.g., `dspace-v3.<your-domain>`) to the Service URL shown
   above: `http://traefik.kube-system.svc.cluster.local:80`.

## Validate end-to-end
1. Confirm the Tunnel Pods stay Ready and connected (see `/ready` above).
2. Through Cloudflare, browse to your hostname and hit a trivial path that Traefik serves (for
   example, a `/ping` or other health endpoint exposed by your ingress). The request should reach
   the cluster via Cloudflare Tunnel and succeed over HTTP.
