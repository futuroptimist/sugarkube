# Cloudflare Tunnel (cloudflared) for staging

We use **Cloudflare Tunnel** to expose the k3s/Sugarkube cluster to the internet without opening
inbound firewall ports. The canonical staging hostname for dspace is

```
https://staging.democratized.space
```

The tunnel routes this hostname to Traefik (or another ingress controller) running inside the k3s
cluster. You do **not** need to install or run `cloudflared` on your workstation; the connector runs
inside the cluster.

## Prerequisites

- A Cloudflare account.
- A domain added as an active zone in Cloudflare and using Cloudflare nameservers (for example,
  `democratized.space`).
- `staging.democratized.space` (or your staging hostname) is already managed by Cloudflare DNS.
- Access to the Cloudflare Zero Trust / Cloudflare One dashboard.
- A running k3s cluster with Sugarkube and Traefik installed (see the main Sugarkube docs for the
  setup steps).
- You plan to publish a public HTTP application, not a private-only Zero Trust app.

Read more in the Cloudflare docs: the
[Cloudflare Tunnel overview](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/)
and
[Get started with Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/).

## Names, environments, and tokens

Three names/identifiers come into play:

- **Cloudflare tunnel name** (for example, `dspace-staging-v3`): lives only in Cloudflare and is
  bound to the connector token (JWT) you copy from the dashboard.
- **Sugarkube `env`** (for example, `dev`, `staging`): controls how Sugarkube labels and names
  resources on the k3s cluster. It does not change which Cloudflare tunnel you connect to.
- **CF_TUNNEL_NAME**: optional override that forces Sugarkube to use a specific Cloudflare tunnel
  name inside the ConfigMap and Helm values instead of the default `sugarkube-<env>`.

The connector token (JWT) is the canonical binding between the cluster and the Cloudflare tunnel.
You can safely run:

```bash
# CF_TUNNEL_TOKEN should already be set to the connector JWT from the Cloudflare dashboard
export CF_TUNNEL_NAME="dspace-staging-v3"
just cf-tunnel-install env=dev
```

and the connector will still attach to the `dspace-staging-v3` tunnel because the token +
CF_TUNNEL_NAME pair decides which tunnel Cloudflare routes,
regardless of the Sugarkube `env`.
This remains correct for traffic bound for `staging.democratized.space` because that hostname is
attached to the Cloudflare tunnel, not the Sugarkube environment name.

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
   - If the dashboard shows a command like `cloudflared service install <tunnel-token>`, copy the
     `<tunnel-token>` portion (not the whole command) and store it securely. We will pass it to
     `just cf-tunnel-install` in the cluster.

Refer to Cloudflare’s guide for full details:
[Create a tunnel in the dashboard](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/).

## Step 2 – Run `cloudflared` in the cluster (connector)

This is the “Install and run a connector” step from the Cloudflare UI. It must run on a node in the
k3s cluster (for example, `sugarkube0`), **not** on your workstation. `just cf-tunnel-install` is
the canonical way to install the connector on the Pi. The recipe now deploys Cloudflare’s
**token-based connector mode** (JWT from the dashboard), so no origin certificates or
`credentials.json` files are required.

### Deploy the Helm chart via Sugarkube

1. Export the tunnel token from Step 1 (add optional name and ID overrides to keep dashboard names
   aligned):
   ```bash
   export CF_TUNNEL_TOKEN="<tunnel-token>"
   export CF_TUNNEL_NAME="<dashboard-tunnel-name>"   # Optional: overrides sugarkube-<env>
   export CF_TUNNEL_ID="<dashboard-tunnel-id>"        # Optional: helps keep names aligned
   ```
2. Install or update the chart and Secret on the cluster (the namespace is created if needed):
   ```bash
   just cf-tunnel-install env=staging
   ```
   The recipe reads `CF_TUNNEL_TOKEN` when set and also strips common prefixes such as
   `token <jwt>`, `TUNNEL_TOKEN <jwt>`, or a full `cloudflared ... --token <jwt>` command if you
   pass the token explicitly. The Secret is mounted directly into the Deployment as `TUNNEL_TOKEN`,
   and the chart is patched to run `cloudflared tunnel run --token "$TUNNEL_TOKEN"` with
   metrics/readiness on `:2000`.
3. Verify readiness (Pods should report `/ready` = `200`):
   ```bash
   kubectl -n cloudflare get deploy,po -l app.kubernetes.io/name=cloudflare-tunnel
   kubectl -n cloudflare exec deploy/cloudflare-tunnel -- curl -fsS http://localhost:2000/ready
   ```
   `curl http://localhost:2000/ready` returning `200` means the connector is up and Cloudflare can
   reach this cluster.

### Worked example: dspace staging tunnel on sugarkube0 (env=dev)

Below is the full sequence for deploying the dspace staging connector on the primary control-plane
node while the Sugarkube environment is `dev`.

```bash
# SSH into the control-plane node
ssh sugarkube0

# Navigate to the Sugarkube checkout
cd ~/sugarkube

# Token copied from the Cloudflare dashboard command snippet for the dspace-staging-v3 tunnel
export CF_TUNNEL_TOKEN="<tunnel-token>"

# Optional: keep tunnel names aligned with the dashboard
export CF_TUNNEL_NAME="dspace-staging-v3"
export CF_TUNNEL_ID="<dashboard-tunnel-id>"

# Install the connector for the dev Sugarkube environment while using the staging tunnel
just cf-tunnel-install env=dev

# Verify the connector is healthy
kubectl -n cloudflare get deploy,po -l app.kubernetes.io/name=cloudflare-tunnel
kubectl -n cloudflare exec deploy/cloudflare-tunnel -- curl -fsS http://localhost:2000/ready
```

> **Tip**: Replace the placeholder values above with the real token and ID from your Cloudflare
> dashboard.

If the pod logs ever show `Cannot determine default origin certificate path`, the deployment is
still trying to use the legacy origin-cert / `credentials.json` flow. Re-run `just cf-tunnel-install`
to reapply the token-based patch; the recipe overwrites `config.yaml` to remove
`credentials-file` and forces the Deployment to run
`cloudflared ... --token "$TUNNEL_TOKEN"`.

Once `cloudflared` is running with the correct token, Cloudflare links the named tunnel to the
cluster so requests to `staging.democratized.space` reach Traefik.

## Step 3 – Publish the staging application (route to Traefik)

Now that the connector is running in the cluster, configure the route from your staging hostname to
the internal Traefik Service.

1. In the tunnel configuration, open the **Public hostnames**, **Application routes**, or
   **Published applications** section.
2. Add a new route/application:
   - **Hostname**: `staging.democratized.space`
   - **Service type**: `HTTP`
   - **Service URL**: `http://traefik.<namespace>.svc.cluster.local:80`

   Replace `<namespace>` with the namespace used by Traefik (commonly `kube-system`) or your chosen
   ingress controller inside the k3s cluster.
3. Save the route. This sends HTTPS traffic for `staging.democratized.space` through the tunnel into
   the Traefik ClusterIP service in your k3s cluster.

See Cloudflare’s docs for the latest UI steps:
[Publish an application through Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/#publish-an-application).

## Step 4 – Verify / create DNS record for the staging subdomain

The `staging.democratized.space` hostname is already managed by Cloudflare DNS. When you publish a
hostname through the tunnel UI, Cloudflare **usually** creates a proxied CNAME automatically that
points `staging.democratized.space` to your tunnel’s `*.cfargotunnel.com` address.

If you see a DNS record for `staging.democratized.space` pointing at `<UUID>.cfargotunnel.com`,
you’re done.

### Manual creation (fallback)

Only create this manually if the CNAME is missing:

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

- A named Cloudflare Tunnel exists (for example, `dspace-staging-k3s`) with a saved token.
- `cloudflared` runs inside the k3s cluster via `just cf-tunnel-install` using that token.
- A route maps `staging.democratized.space` to
  `http://traefik.<namespace>.svc.cluster.local:80` inside the cluster.
- Cloudflare DNS has (or auto-created) a proxied CNAME pointing `staging.democratized.space` to the
  tunnel’s `*.cfargotunnel.com` name.
- The Sugarkube dspace app expects this persistent tunnel setup to be in place.
