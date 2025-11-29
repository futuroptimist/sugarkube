# Cloudflare Tunnel (cloudflared) for staging

We use **Cloudflare Tunnel** to expose the k3s/Sugarkube cluster to the internet without opening
inbound firewall ports. The canonical staging hostname for dspace is

```
https://staging.democratized.space
```

The tunnel routes this hostname to Traefik (or another ingress controller) running inside the k3s
cluster. You do **not** need to install or run `cloudflared` on your workstation; the connector runs
inside the cluster.

Cloudflare has two big modes: **remotely-managed** tunnels (created in the dashboard, run with a
single tunnel token) and **locally-managed** tunnels (created with `cloudflared login` and a
`cert.pem`). Sugarkube only uses the remotely-managed, **token-only** model described here.

## TL;DR checklist (skim this first)

- Create a remotely-managed tunnel in the Cloudflare dashboard and note its name (for example,
  `dspace-staging-v3`).
- On the tunnel’s **Install and run a connector** panel, copy the tunnel token (`eyJ...`) from any of
  the OS-specific commands.
- On `sugarkube0`, export `CF_TUNNEL_TOKEN` (and optionally `CF_TUNNEL_NAME`), then run:
  `just cf-tunnel-install env=dev token="$CF_TUNNEL_TOKEN"`.
- In the tunnel UI, create a **Public hostname** mapping
  `staging.democratized.space` → `http://traefik.<namespace>.svc.cluster.local:80`.
- Confirm the connector is healthy:
  `kubectl -n cloudflare exec deploy/cloudflare-tunnel -- curl -fsS http://localhost:2000/ready`.

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
2. Navigate to **Networks → Tunnels** (or **Connectors → Cloudflare Tunnels**, depending on the
   current UI).
3. Click **Create a tunnel**.
4. Choose **Cloudflared** as the connector type.
5. Name the tunnel (for example, `dspace-staging-v3`).
6. Click **Save tunnel**. You will see an **Install and run a connector** panel with OS-specific
   commands. They all embed the **same tunnel token**. Examples:

   ```bash
   sudo cloudflared service install <TUNNEL_TOKEN>
   cloudflared tunnel run --token <TUNNEL_TOKEN>
   ```

   The only part Sugarkube needs is `<TUNNEL_TOKEN>`—the long string starting with `eyJ...`. Copy the
   token from **any** command on this page and ignore the rest. Do **not** run these installer
   commands on your workstation or Pi.

Refer to Cloudflare’s guide for full details:
[Create a tunnel in the dashboard](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/).

## Step 2 – Run `cloudflared` in the cluster (connector)

This is the “Install and run a connector” step, but executed by Sugarkube on the k3s cluster. The
Helm recipe deploys Cloudflare’s remotely-managed, token-only connector mode: the pod sets
`TUNNEL_TOKEN` from the `tunnel-token` Secret and runs `cloudflared tunnel --no-autoupdate --metrics
0.0.0.0:2000 run` with **no** `cert.pem` or `credentials.json`.

### Names, environments, and how tunnels are selected

- **Cloudflare tunnel name** (for example, `dspace-staging-v3`): defined in the Cloudflare dashboard
  and tied to the token you copied.
- **Sugarkube `env`** (for example, `dev`, `staging`): affects Sugarkube naming/labels, including the
  default tunnel name `sugarkube-<env>`, but does **not** decide which Cloudflare tunnel you join.
- **CF_TUNNEL_NAME**: optionally overrides the Sugarkube default so the in-cluster name matches the
  Cloudflare dashboard name.

Examples:

| Sugarkube env | CF_TUNNEL_NAME       | Cloudflare tunnel joined |
| ------------- | -------------------- | ------------------------ |
| dev           | (unset)              | `sugarkube-dev`          |
| dev           | dspace-staging-v3    | `dspace-staging-v3`      |
| staging       | dspace-staging-v3    | `dspace-staging-v3`      |

The tunnel **token + CF_TUNNEL_NAME** select the Cloudflare tunnel. Sugarkube’s `env` only controls
labels and defaults.

### Deploy the Helm chart via Sugarkube

Run these commands on the primary node (for example, `sugarkube0`):

1. Point `kubectl` at the cluster and move to the Sugarkube checkout:
   ```bash
   export KUBECONFIG="$HOME/.kube/config"
   cd ~/sugarkube
   ```
2. Export the tunnel token (and optional naming overrides) exactly as shown in the dashboard. The
   token is the `eyJ...` value embedded in any installer command:
   ```bash
   export CF_TUNNEL_TOKEN="eyJ...copy-pasted-from-dashboard..."
   export CF_TUNNEL_NAME="dspace-staging-v3"   # Optional: match the dashboard name
   export CF_TUNNEL_ID="<dashboard-tunnel-id>" # Optional: informative only
   ```
   `env=dev`/`env=staging` here refers to the Sugarkube environment name, not a Cloudflare concept.
3. Install or update the chart and Secret on the cluster (namespace is created if needed):
   ```bash
   just cf-tunnel-install env=dev token="$CF_TUNNEL_TOKEN"
   ```
   Omitting `token=` falls back to `CF_TUNNEL_TOKEN` in the environment, but passing it explicitly
   keeps the intent obvious. The recipe strips common prefixes (like `token=<jwt>` or a full
   `cloudflared ... --token <jwt>` command) and mounts the Secret directly as `TUNNEL_TOKEN`.
4. Verify readiness (Pods should report `/ready` = `200`):
   ```bash
   kubectl -n cloudflare get deploy,po -l app.kubernetes.io/name=cloudflare-tunnel
   kubectl -n cloudflare exec deploy/cloudflare-tunnel -- curl -fsS http://localhost:2000/ready
   ```
   `curl http://localhost:2000/ready` returning `200` means the connector is up and Cloudflare can
   reach this cluster.

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
an acceptable way to recover without losing the saved token.

### Worked example: dspace staging tunnel on the `dev` Sugarkube env

Below is the full sequence for deploying the `dspace-staging-v3` tunnel on the primary control-plane
node while keeping the Sugarkube environment set to `dev`:

```bash
# On sugarkube0
export KUBECONFIG="$HOME/.kube/config"
cd ~/sugarkube

# Connector token from the Cloudflare dashboard for the dspace-staging-v3 tunnel.
# Copy only the long eyJ... token from any installer command on the page.
export CF_TUNNEL_TOKEN="<CONNECTOR_TOKEN for dspace-staging-v3>"

# Keep names aligned with the Cloudflare dashboard (optional but recommended)
export CF_TUNNEL_NAME="dspace-staging-v3"

# Run the installer against the dev Sugarkube environment
just cf-tunnel-install env=dev token="$CF_TUNNEL_TOKEN"

# Sanity check: make sure the pod is up and ready
kubectl -n cloudflare get pods
kubectl -n cloudflare exec deploy/cloudflare-tunnel -- curl -fsS http://localhost:2000/ready
```

Even though the Sugarkube environment is `dev`, this connects the cluster to the
`dspace-staging-v3` tunnel because both the tunnel token and `CF_TUNNEL_NAME` come from that tunnel
in the Cloudflare dashboard. If you prefer a matching Sugarkube environment, switch `env=dev` to
`env=staging` while keeping the same token and `CF_TUNNEL_NAME` values.

If the pod logs ever show errors like:

```text
Cannot determine default origin certificate path. No file cert.pem ...
error parsing tunnel ID: Error locating origin cert: client didn't specify origincert path
```

`cloudflared` is trying to start in the **legacy, locally-managed** mode (expects `cert.pem` or
`TUNNEL_ORIGIN_CERT`) instead of the remote-managed token-only mode. Common causes include:

- The tunnel was originally created as a locally-managed tunnel (using certs) rather than in the
  dashboard flow above.
- The Deployment references an old config file or Secret that implies a locally-managed tunnel.
- The Secret or environment variable does not contain the tunnel token for this tunnel (for example,
  it’s a different API token or a token from another tunnel).

To fix it:

1. Double-check that you created the tunnel in the dashboard as described in Step 1 (remotely
   managed).
2. Regenerate or recopy the tunnel token from **Edit tunnel → Install and run a connector**, paste it
   into `CF_TUNNEL_TOKEN`, then run:
   ```bash
   just cf-tunnel-reset
   just cf-tunnel-install env=dev token="$CF_TUNNEL_TOKEN"
   ```
3. If in doubt, delete and recreate the tunnel in the dashboard using the current remotely-managed
   flow, then update the token in your cluster.

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

- A named Cloudflare Tunnel exists (for example, `dspace-staging-v3`) with a saved token.
- `cloudflared` runs inside the k3s cluster via `just cf-tunnel-install` using that token.
- A route maps `staging.democratized.space` to
  `http://traefik.<namespace>.svc.cluster.local:80` inside the cluster.
- Cloudflare DNS has (or auto-created) a proxied CNAME pointing `staging.democratized.space` to the
  tunnel’s `*.cfargotunnel.com` name.
- The Sugarkube dspace app expects this persistent tunnel setup to be in place.
