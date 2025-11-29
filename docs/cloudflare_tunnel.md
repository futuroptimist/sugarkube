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

## Step 1 – Create a tunnel in Cloudflare

1. Log in to the Cloudflare Zero Trust / One dashboard.
2. Navigate to **Networks → Tunnels** (or **Connectors → Cloudflare Tunnel**, depending on the
   current UI).
3. Click **Create a tunnel**.
4. Choose **Cloudflared** as the connector type.
5. Name the tunnel (for example, `dspace-staging-k3s`).
6. Click **Save tunnel**. The dashboard will show multiple OS-specific snippets that contain a
   tunnel token. **Do not run these commands on your workstation**; copy the token for use with
   Sugarkube in Step 2.
   - The snippet we want looks like:

     ```bash
     cloudflared tunnel --no-autoupdate run --token <CONNECTOR_TOKEN>
     ```

     Copy **only** the `<CONNECTOR_TOKEN>` (the JWT that usually starts with `eyJ`), not the whole
     command.
   - Ignore snippets such as `cloudflared service install <TOKEN>`; those tokens are not valid for
     `cloudflared tunnel run --token` and will trigger origin-cert errors in the cluster.

Refer to Cloudflare’s guide for full details:
[Create a tunnel in the dashboard](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/).

## Step 2 – Run `cloudflared` in the cluster (connector)

This is the “Install and run a connector” step from the Cloudflare UI. It must run on a node in the
k3s cluster (for example, `sugarkube0`), **not** on your workstation. `just cf-tunnel-install` is
the canonical way to install the connector on the Pi. The recipe now deploys Cloudflare’s
**token-based connector mode** (connector token (JWT) from the dashboard), so no origin
certificates or `credentials.json` files are required.

Cloudflare shows several commands that embed tokens. For `CF_TUNNEL_TOKEN`, copy **only** the token
from the snippet that looks like:

```bash
cloudflared tunnel --no-autoupdate run --token <CONNECTOR_TOKEN>
```

Do **not** paste the `token=` prefix, the whole command, or a token from `cloudflared service
install <TOKEN>`—those will make `cloudflared` fall back to the legacy origin-certificate flow.

> **Common pitfalls**
>
> - Copying the token from a `cloudflared service install <TOKEN>` snippet instead of the
>   `cloudflared tunnel --no-autoupdate run --token <CONNECTOR_TOKEN>` snippet.
> - Including the `token=` prefix or the entire command instead of just `<CONNECTOR_TOKEN>`.
> - Using a token for a different tunnel than the one configured for `staging.democratized.space`.
>
> If `cf-tunnel-install` fails and the pod logs mention:
>
> ```text
> Cannot determine default origin certificate path. No file cert.pem ...
> error parsing tunnel ID: Error locating origin cert: client didn't specify origincert path
> ```
>
> it almost always means the provided token is not valid for `cloudflared tunnel run --token`. In
> that case, regenerate or recopy the connector token from the correct snippet and run:
>
> ```bash
> just cf-tunnel-reset
> just cf-tunnel-install env=dev token="$CF_TUNNEL_TOKEN"
> ```

### Names, environments, and how tunnels are selected

- **Cloudflare tunnel name** (for example, `dspace-staging-v3`): defined in the Cloudflare dashboard
  and tied to the connector token you copy.
- **Sugarkube `env`** (for example, `dev`, `staging`): affects Sugarkube naming/labels, including the
  default tunnel name `sugarkube-<env>`, but does **not** decide which Cloudflare tunnel you join.
- **CF_TUNNEL_NAME**: optionally overrides the Sugarkube default so the in-cluster name matches the
  Cloudflare dashboard name.

The **connector token (JWT) + `CF_TUNNEL_NAME`** determine the Cloudflare tunnel the cluster joins.
It is safe to run a staging tunnel on a cluster whose Sugarkube `env` is `dev` so long as both the
token and `CF_TUNNEL_NAME` come from that staging tunnel in the dashboard. Sugarkube’s `env`
controls labels and defaults; the tunnel token controls connectivity.

### Deploy the Helm chart via Sugarkube

This is the canonical set of commands to run on the Pi; the naming rules above explain how the
Cloudflare tunnel, Sugarkube `env`, and `CF_TUNNEL_NAME` interact.

1. Point `kubectl` at the cluster and move to the Sugarkube checkout:
   ```bash
   export KUBECONFIG="$HOME/.kube/config"
   cd ~/sugarkube
   ```
2. Export the connector token (and optional naming overrides) from the Cloudflare dashboard entry
   for your tunnel:
   ```bash
   export CF_TUNNEL_TOKEN="<tunnel-token>"
   export CF_TUNNEL_NAME="dspace-staging-v3"   # Optional override to match the dashboard name
   export CF_TUNNEL_ID="<dashboard-tunnel-id>" # Optional: helpful for alignment, not required
   ```
3. Install or update the chart and Secret on the cluster (namespace is created if needed):
   ```bash
   just cf-tunnel-install env=dev token="$CF_TUNNEL_TOKEN"
   ```
   Omitting the `token=` argument falls back to `CF_TUNNEL_TOKEN` in the environment, but passing it
   explicitly keeps the intent obvious. The recipe strips common prefixes (`token=<jwt>`,
   `TUNNEL_TOKEN=<jwt>`, or a full `cloudflared ... --token <jwt>` command) and mounts the Secret
   directly as `TUNNEL_TOKEN`. The chart is patched to run `cloudflared tunnel run --token
   "$TUNNEL_TOKEN"` with metrics/readiness on `:2000` and **no** `credentials.json` or origin cert
   references.
4. Verify readiness (Pods should report `/ready` = `200`):
   ```bash
   kubectl -n cloudflare get deploy,po -l app.kubernetes.io/name=cloudflare-tunnel
   kubectl -n cloudflare exec deploy/cloudflare-tunnel -- curl -fsS http://localhost:2000/ready
   ```
   `curl http://localhost:2000/ready` returning `200` means the connector is up and Cloudflare can
   reach this cluster.

### Recovery and reset

If rollout gets stuck (CrashLoopBackOff, old ReplicaSets, etc.), use the built-in teardown helpers
to return to a clean token-mode state:

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

The installer now performs a teardown-and-retry if the first rollout fails, so rerunning the recipes
is the canonical way to recover a wedged connector without losing the saved JWT.

### Worked example: dspace staging tunnel on the `dev` Sugarkube env

Below is the full sequence for deploying the `dspace-staging-v3` tunnel on the primary
control-plane node while keeping the Sugarkube environment set to `dev`:

```bash
# On sugarkube0
export KUBECONFIG="$HOME/.kube/config"

cd ~/sugarkube

# Connector token copied from the `cloudflared tunnel --no-autoupdate run --token <CONNECTOR_TOKEN>`
# snippet for the dspace-staging-v3 tunnel
export CF_TUNNEL_TOKEN="<tunnel-token for dspace-staging-v3>"

# Keep names aligned with the Cloudflare dashboard
export CF_TUNNEL_NAME="dspace-staging-v3"
# (Optional) CF_TUNNEL_ID if helpful, but not required

# Run the installer against the dev Sugarkube environment
just cf-tunnel-install env=dev token="$CF_TUNNEL_TOKEN"
```

Even though the Sugarkube environment is `dev`, this connects the cluster to the `dspace-staging-v3`
tunnel and routes `staging.democratized.space` because both the connector token and
`CF_TUNNEL_NAME` come from that tunnel in the Cloudflare dashboard. If you prefer a matching
Sugarkube environment, switch `env=dev` to `env=staging` while keeping the same token and
`CF_TUNNEL_NAME` values.

If the pod logs show `Cannot determine default origin certificate path`, the deployment is still
trying to use the legacy origin-cert / `credentials.json` flow. Recopy the connector token from the
`cloudflared tunnel --no-autoupdate run --token <CONNECTOR_TOKEN>` snippet, then run:

```bash
just cf-tunnel-reset
just cf-tunnel-install env=dev token="$CF_TUNNEL_TOKEN"
```

The recipe removes any `credentials-file` references and forces `cloudflared tunnel run --token
"$TUNNEL_TOKEN"`.

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
