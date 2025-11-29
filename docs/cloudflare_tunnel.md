# Cloudflare Tunnel (cloudflared) for staging

We use **Cloudflare Tunnel** to expose the k3s/Sugarkube cluster to the internet without opening
inbound firewall ports. The canonical staging hostname for dspace is

```
https://staging.democratized.space
```

The tunnel routes this hostname to Traefik (or another ingress controller) running inside the k3s
cluster. You do **not** need to install or run `cloudflared` on your workstation; the connector runs
inside the cluster.

> Cloudflare has two big modes for tunnels: **remotely-managed** (token-only, created in the
> dashboard) and **locally-managed** (requires `cloudflared login` and a `cert.pem`). Sugarkube uses
> the **remotely-managed** model only. If you create the tunnel in the Cloudflare dashboard as shown
> below, you are already using the correct mode.

## TL;DR checklist

- Create a remotely-managed tunnel in the Cloudflare dashboard and note its name.
- Copy the tunnel token (`eyJ...`) from the **Install and run a connector** panel.
- On `sugarkube0`, export `CF_TUNNEL_TOKEN` and (optionally) `CF_TUNNEL_NAME`, then run:
  `just cf-tunnel-install env=dev token="$CF_TUNNEL_TOKEN"`.
- In the tunnel UI, configure a Public hostname routing `staging.democratized.space` →
  `http://traefik.<namespace>.svc.cluster.local:80`.
- Confirm readiness: `kubectl -n cloudflare exec deploy/cloudflare-tunnel -- curl -fsS http://localhost:2000/ready`
  should return HTTP 200.

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

## Step 1 – Create a remotely-managed tunnel in Cloudflare

1. Log in to the Cloudflare Zero Trust / One dashboard.
2. Navigate to **Networks → Tunnels** (or **Connectors → Cloudflare Tunnel**, depending on the
   current UI).
3. Click **Create a tunnel**.
4. Choose **Cloudflared** as the connector type.
5. Name the tunnel (for example, `dspace-staging-v3`). This can be any unique name.
6. Click **Save tunnel**. The dashboard opens **Install and run a connector** with OS-specific
   commands. **Ignore the OS install commands and do not run `curl | sudo bash` on your Pi.**
   Sugarkube will run `cloudflared` inside the cluster for you. Your only job here is to copy the
   tunnel token from this page.

   All the commands shown (Windows/Mac/Debian/Docker, etc.) embed **the same** tunnel token. The
   panel usually shows snippets such as:

   ```bash
   sudo cloudflared service install <TUNNEL_TOKEN>
   cloudflared tunnel run --token <TUNNEL_TOKEN>
   ```

   The only part Sugarkube needs is `<TUNNEL_TOKEN>` – the long string starting with `eyJ...`. You
   can copy it from **any** of the commands on this page; they all use the same token. Copy only the
   token value, not the whole command.

Refer to Cloudflare’s guide for full details:
[Create a tunnel in the dashboard](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/).

## Step 2 – Run `cloudflared` in the cluster (connector)

This is the “Install and run a connector” step from the Cloudflare UI. It must run on a node in the
k3s cluster (for example, `sugarkube0`), **not** on your workstation. `just cf-tunnel-install` is
the canonical way to install the connector on the Pi. The recipe deploys Cloudflare’s
**token-only, remote-managed** mode: the pod sets `TUNNEL_TOKEN` from the `tunnel-token` Secret and
runs `cloudflared tunnel --no-autoupdate --metrics 0.0.0.0:2000 run` with **no** `cert.pem` or
`credentials.json`.

### Names, environments, and how tunnels are selected

- **Cloudflare tunnel name** (for example, `dspace-staging-v3`): defined in the Cloudflare dashboard
  and tied to the tunnel token you copy.
- **Sugarkube `env`** (for example, `dev`, `staging`): sets Sugarkube naming/labels, including the
  default tunnel name `sugarkube-<env>`, but does **not** decide which Cloudflare tunnel you join.
- **CF_TUNNEL_NAME**: optional override so the in-cluster name matches the Cloudflare dashboard
  name. If unset, Sugarkube defaults to `sugarkube-<env>`.

The **tunnel token + `CF_TUNNEL_NAME`** determine which Cloudflare tunnel the cluster connects to. It
is safe to run a staging tunnel on a cluster whose Sugarkube `env` is `dev` as long as both the token
and `CF_TUNNEL_NAME` come from that staging tunnel in the dashboard. Sugarkube’s `env` controls
labels and defaults; the token controls connectivity.

Examples:

| Sugarkube env | CF_TUNNEL_NAME          | Resulting tunnel joined            |
|---------------|-------------------------|------------------------------------|
| dev           | (unset)                 | `sugarkube-dev`                    |
| dev           | dspace-staging-v3       | `dspace-staging-v3` (dashboard)    |
| staging       | dspace-staging-v3       | `dspace-staging-v3` (dashboard)    |

### Deploy the Helm chart via Sugarkube

Run these commands on `sugarkube0` (or whichever node has the Sugarkube checkout):

1. Point `kubectl` at the cluster and move to the Sugarkube checkout:

   ```bash
   export KUBECONFIG="$HOME/.kube/config"
   cd ~/sugarkube
   ```

2. Export the tunnel token from the Cloudflare dashboard. This is the `eyJ...` value embedded in the
   commands shown after creating the tunnel. Copy it from any snippet on the **Install and run a
   connector** panel:

   ```bash
   export CF_TUNNEL_TOKEN="eyJ...copy-pasted-from-dashboard..."
   export CF_TUNNEL_NAME="dspace-staging-v3"   # Optional override to match the dashboard name
   export CF_TUNNEL_ID="<dashboard-tunnel-id>" # Optional: helpful for alignment, not required
   ```

   `CF_TUNNEL_NAME` only affects naming inside Kubernetes; connectivity is driven by the tunnel token.

3. Install or update the chart and Secret on the cluster (namespace is created if needed). `env=dev`
   or `env=staging` refers to the Sugarkube environment name, not a Cloudflare concept:

   ```bash
   just cf-tunnel-install env=dev token="$CF_TUNNEL_TOKEN"
   ```

   Passing `token=` explicitly keeps the intent obvious. The recipe strips common prefixes
   (`token=<jwt>`, `TUNNEL_TOKEN=<jwt>`, or a full `cloudflared ... --token <jwt>` command) and mounts
   the Secret directly as `TUNNEL_TOKEN`.

4. Verify readiness (Pods should report `/ready` = `200`):

   ```bash
   kubectl -n cloudflare get deploy,po -l app.kubernetes.io/name=cloudflare-tunnel
   kubectl -n cloudflare exec deploy/cloudflare-tunnel -- curl -fsS http://localhost:2000/ready
   ```

   `curl http://localhost:2000/ready` returning `200` means the connector is up and Cloudflare can
   reach this cluster.

### Worked example: dspace staging tunnel on the `dev` Sugarkube env

Below is the full sequence for deploying the `dspace-staging-v3` tunnel on the primary control-plane
node while keeping the Sugarkube environment set to `dev`:

```bash
# On sugarkube0
export KUBECONFIG="$HOME/.kube/config"

cd ~/sugarkube

# Copy the tunnel token (the long eyJ... string) from the dashboard's
# "Install and run a connector" panel for dspace-staging-v3. Any command on that panel contains it.
export CF_TUNNEL_TOKEN="<TUNNEL_TOKEN for dspace-staging-v3>"

# Keep names aligned with the Cloudflare dashboard
export CF_TUNNEL_NAME="dspace-staging-v3"
# (Optional) CF_TUNNEL_ID if helpful, but not required

# Run the installer against the dev Sugarkube environment
just cf-tunnel-install env=dev token="$CF_TUNNEL_TOKEN"

# Sanity check: connector pod should be ready
kubectl -n cloudflare get pods -l app.kubernetes.io/name=cloudflare-tunnel
kubectl -n cloudflare exec deploy/cloudflare-tunnel -- curl -fsS http://localhost:2000/ready
```

Even though the Sugarkube environment is `dev`, this connects the cluster to the `dspace-staging-v3`
tunnel and routes `staging.democratized.space` because both the tunnel token and `CF_TUNNEL_NAME`
come from that tunnel in the Cloudflare dashboard. If you prefer a matching Sugarkube environment,
switch `env=dev` to `env=staging` while keeping the same token and `CF_TUNNEL_NAME` values.

### If you see origin certificate errors

Errors like:

```text
Cannot determine default origin certificate path. No file cert.pem ...
error parsing tunnel ID: Error locating origin cert: client didn't specify origincert path
```

mean `cloudflared` is trying to run in the legacy **locally-managed** mode that expects
`cert.pem` / `TUNNEL_ORIGIN_CERT`, not the token-only remote-managed mode used by Sugarkube. Likely
causes include:

- The tunnel in Cloudflare was created as a locally-managed tunnel (not via the dashboard flow
  above).
- The Kubernetes Deployment still references a config file or Secret meant for locally-managed
  tunnels.
- The environment variable or Secret does not actually contain the tunnel token for this tunnel (for
  example, a different API token or a token from another tunnel).

To fix:

- Double-check that you created the tunnel in the dashboard as described in Step 1 (remotely
  managed).
- Regenerate or recopy the tunnel token from the **Edit tunnel → Install and run a connector** page,
  paste it into `CF_TUNNEL_TOKEN`, then rerun:

  ```bash
  just cf-tunnel-reset
  just cf-tunnel-install env=dev token="$CF_TUNNEL_TOKEN"
  ```

- If in doubt, delete and recreate the tunnel in the dashboard using the current remotely-managed
  flow, then update the token in your cluster.

Once `cloudflared` runs with the correct token, Cloudflare links the named tunnel to the cluster so
requests to `staging.democratized.space` reach Traefik.

### Recovery and reset

If rollout gets stuck (CrashLoopBackOff, old ReplicaSets, etc.), use the built-in teardown helpers to
return to a clean token-mode state:

- Inspect status and logs:

  ```bash
  just cf-tunnel-debug
  ```

- Hard reset the deployment/configmap/pods while preserving the `tunnel-token` Secret:

  ```bash
  just cf-tunnel-reset
  ```

  This is safe to re-run; uncomment the Secret delete inside the recipe only if you intentionally
  want to remove the stored token.

- Reinstall in token mode after a reset:

  ```bash
  just cf-tunnel-install env=dev token="$CF_TUNNEL_TOKEN"
  ```

The installer performs a teardown-and-retry if the first rollout fails, so rerunning the recipes is
the canonical way to recover a wedged connector without losing the saved token.

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

- A named Cloudflare Tunnel exists (for example, `dspace-staging-v3`) with a saved token.
- `cloudflared` runs inside the k3s cluster via `just cf-tunnel-install` using that token.
- A route maps `staging.democratized.space` to
  `http://traefik.<namespace>.svc.cluster.local:80` inside the cluster.
- Cloudflare DNS has (or auto-created) a proxied CNAME pointing `staging.democratized.space` to the
  tunnel’s `*.cfargotunnel.com` name.
- The Sugarkube dspace app expects this persistent tunnel setup to be in place.
