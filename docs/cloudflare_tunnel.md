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

## Step 1 – Create a tunnel in Cloudflare

1. Log in to the Cloudflare Zero Trust / One dashboard.
2. Navigate to **Networks → Tunnels** (or **Connectors → Cloudflare Tunnel**, depending on the
   current UI).
3. Click **Create a tunnel**.
4. Choose **Cloudflared** as the connector type.
5. Name the tunnel (for example, `dspace-staging-k3s`).
6. Click **Save tunnel**. The dashboard will show OS-specific commands (Windows/Mac/Debian/Docker,
   etc.) that include a tunnel token. **Do not run these commands on your workstation**; we will use
   the token with Sugarkube in Step 2.
   - If the dashboard shows `cloudflared service install <tunnel-token>`, copy the
     `<tunnel-token>` part (not the whole command) and store it somewhere safe. We will pass it to
     `just cf-tunnel-install` on the cluster.

Refer to Cloudflare’s guide for full details:
[Create a tunnel in the dashboard](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/).

## Step 2 – Run `cloudflared` in the cluster (connector)

This is the "Install and run a connector" step from the Cloudflare UI. It must run on a node in the
k3s cluster (for example, `sugarkube0`), not on your workstation.

### Deploy the Helm chart via Sugarkube

1. Export the tunnel token from Step 1 (add optional name and ID overrides to keep dashboard names
   aligned):
   ```bash
   export CF_TUNNEL_TOKEN="<tunnel-token>"
   export CF_TUNNEL_NAME="<dashboard-tunnel-name>"   # Optional: overrides sugarkube-<env>
   export CF_TUNNEL_ID="<dashboard-tunnel-id>"        # Optional: helps keep names aligned
   ```
   - `CF_TUNNEL_TOKEN` is the value shown in the Cloudflare dashboard command output (for example,
     the token inside `cloudflared service install <tunnel-token>`).
2. Install or update the chart and Secret on the cluster (the namespace is created if needed):
   ```bash
   just cf-tunnel-install env=dev token="$CF_TUNNEL_TOKEN"
   ```
3. Verify readiness (Pods should report `/ready` = `200`; `curl http://localhost:2000/ready`
   returning `200` means the connector is up and Cloudflare can reach this cluster):
   ```bash
   kubectl -n cloudflare get deploy,po -l app.kubernetes.io/name=cloudflare-tunnel
   kubectl -n cloudflare exec deploy/cloudflare-tunnel -- curl -fsS http://localhost:2000/ready
   ```

Once `cloudflared` is running with the correct token, Cloudflare links the named tunnel to the
cluster so requests to `staging.democratized.space` reach Traefik.

## Step 3 – Publish the staging application (route to Traefik)

Now that the connector is running in the cluster, configure the route from the staging hostname to
the internal Traefik Service.

1. In the tunnel configuration, open the **Public hostnames**, **Application routes**, or
   **Published applications** section.
2. Add a new route/application:
   - **Hostname**: `staging.democratized.space`
   - **Service type**: `HTTP`
   - **Service URL**: `http://traefik.<namespace>.svc.cluster.local:80`

   Replace `<namespace>` with the namespace used by Traefik (commonly `kube-system`) or your chosen
   ingress controller inside the k3s cluster. This sends HTTPS traffic for
   `staging.democratized.space` through the tunnel into the Traefik ClusterIP service in your k3s
   cluster.
3. Save the route.

See Cloudflare’s docs for the latest UI steps:
[Publish an application through Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/#publish-an-application).

## Step 4 – Verify / create DNS record for the staging subdomain

### Automatically created

When you publish a hostname through the tunnel UI, Cloudflare usually creates a proxied CNAME
automatically that points `staging.democratized.space` to your tunnel’s `*.cfargotunnel.com`
address. If you see a DNS record for `staging.democratized.space` pointing at
`<UUID>.cfargotunnel.com`, you’re done.

### Manual creation (fallback)

Only use this if the CNAME is missing. In the Cloudflare dashboard:

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

## Optional: Quick Tunnels for ephemeral previews

For one-off local previews, Cloudflare offers Quick Tunnels on `trycloudflare.com`. They do not
require DNS or a permanent tunnel. This guide focuses on persistent tunnels; use Quick Tunnels only
for temporary local development. See
[Try Cloudflare (Quick Tunnels)](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/).

## Summary

- `staging.democratized.space` is the public staging URL (already managed by Cloudflare DNS).
- A named Cloudflare Tunnel exists in the dashboard with a recorded token.
- `cloudflared` runs in the k3s cluster via `just cf-tunnel-install` using that token.
- The tunnel route maps `staging.democratized.space` to the Traefik ClusterIP service.
- Cloudflare DNS has (or auto-creates) a proxied CNAME pointing `staging` to the tunnel’s
  `*.cfargotunnel.com` name.
- The Sugarkube dspace app expects this persistent tunnel setup to be in place.
