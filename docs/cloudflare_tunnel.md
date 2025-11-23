# Cloudflare Tunnel (cloudflared) for staging

We use **Cloudflare Tunnel** to expose the k3s/Sugarkube cluster to the internet without opening
inbound firewall ports. The canonical staging hostname for dspace is

```
https://staging.democratized.space
```

The tunnel routes this hostname to Traefik (or another ingress controller) running inside the k3s
cluster.

## Prerequisites

- A Cloudflare account.
- A domain added as an active zone in Cloudflare and using Cloudflare nameservers (for example,
  `democratized.space`).
- Access to the Cloudflare Zero Trust / Cloudflare One dashboard.
- A running k3s cluster with Sugarkube and Traefik installed (see the main Sugarkube docs for the
  setup steps).
- You plan to publish a public HTTP application, not a private-only Zero Trust app.

Read more in the Cloudflare docs: the
[Cloudflare Tunnel overview](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/)
and
[Get started with Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/).

## Step 1 – Create a Tunnel

1. Log in to the Cloudflare Zero Trust / One dashboard.
2. Navigate to **Networks → Tunnels** (or **Connectors → Cloudflare Tunnel**, depending on the
   current UI).
3. Click **Create a tunnel**.
4. Choose **Cloudflared** as the connector type.
5. Name the tunnel (for example, `dspace-staging-k3s`).
6. Click **Save tunnel** and follow the UI prompts to install or configure `cloudflared`.

Refer to Cloudflare’s guide for full details:
[Create a tunnel in the dashboard](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/).

If the dashboard shows a Docker or Kubernetes command snippet containing a tunnel token, copy the
token/command somewhere safe. We will use it when wiring the tunnel into the Sugarkube-managed
cluster.

## Step 2 – Publish the staging application

1. In the tunnel configuration, open the **Public hostnames**, **Application routes**, or
   **Published applications** section.
2. Add a new route/application:
   - **Hostname**: `staging.democratized.space`
   - **Service type**: `HTTP`
   - **Service URL**: `http://traefik.<namespace>.svc.cluster.local:80`

   Replace `<namespace>` with the namespace used by Traefik (commonly `kube-system`) or your chosen
   ingress controller inside the k3s cluster.
3. Save the route.

See Cloudflare’s docs for the latest UI steps:
[Publish an application through Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/#publish-an-application).

## Step 3 – DNS record for the staging subdomain

### Automatically created

When you publish a hostname through the tunnel UI, Cloudflare usually creates a CNAME automatically
that points `staging.democratized.space` to your tunnel’s `*.cfargotunnel.com` address.

### Manual creation (if needed)

If the CNAME is missing, create it in the Cloudflare dashboard:

1. Go to **Cloudflare dashboard → DNS → Records** for `democratized.space`.
2. Click **Add record**.
3. Configure the record:
   - **Type**: `CNAME`
   - **Name**: `staging`
   - **Target**: `<UUID>.cfargotunnel.com` (the tunnel hostname shown in the dashboard)
   - **Proxy status**: **Proxied** (orange cloud)
4. Save the record.

Helpful references:
[Create a DNS record for the tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/dns/)
and
[Create subdomain records](https://developers.cloudflare.com/dns/manage-dns-records/how-to/create-subdomain/).

## Step 4 – Run `cloudflared` in the cluster

The `cloudflared` connector must run inside the k3s cluster so the tunnel stays connected. Use the
tunnel token from Step 1 and the Sugarkube automation to deploy it.

### Deploy the Helm chart via Sugarkube

1. Export the tunnel token (add optional name and ID overrides to keep dashboard names aligned):
   ```bash
   export CF_TUNNEL_TOKEN="<tunnel-token>"
   export CF_TUNNEL_NAME="<dashboard-tunnel-name>"   # Optional: overrides sugarkube-<env>
   export CF_TUNNEL_ID="<dashboard-tunnel-id>"        # Optional: helps keep names aligned
   ```
2. Install or update the chart and Secret (the namespace is created if needed):
   ```bash
   just cf-tunnel-install env=dev token="$CF_TUNNEL_TOKEN"
   ```
3. Verify readiness (Pods should report `/ready` = `200`):
   ```bash
   kubectl -n cloudflare get deploy,po -l app.kubernetes.io/name=cloudflare-tunnel
   kubectl -n cloudflare exec deploy/cloudflare-tunnel -- curl -fsS http://localhost:2000/ready
   ```

Once `cloudflared` is running with the correct token, Cloudflare links the named tunnel to the
cluster so requests to `staging.democratized.space` reach Traefik.

## Optional: Quick Tunnels for ephemeral previews

For one-off local previews, Cloudflare offers Quick Tunnels on `trycloudflare.com`. They do not
require DNS or a permanent tunnel. This guide focuses on persistent tunnels; use Quick Tunnels only
for temporary local development. See
[Try Cloudflare (Quick Tunnels)](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/).

## Summary

- `staging.democratized.space` is the public staging URL.
- A named Cloudflare Tunnel routes that hostname to Traefik (or your ingress) inside the k3s
  cluster.
- Cloudflare DNS should contain a proxied CNAME pointing `staging.democratized.space` at the
  tunnel’s `*.cfargotunnel.com` name.
- The Sugarkube dspace app expects this persistent tunnel setup to be in place.
