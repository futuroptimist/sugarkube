# Cloudflare Tunnel (cloudflared) for staging

We use **Cloudflare Tunnel** to expose the k3s/Sugarkube cluster to the internet without opening
inbound firewall ports. The canonical staging hostname for dspace is

```
https://staging.democratized.space
```

The tunnel routes this hostname to Traefik (or another ingress controller) running inside the k3s
cluster. You do **not** need to install or run `cloudflared` on your workstation; the connector runs
inside the cluster.

Cloudflare offers two tunnel modes:
- **Remotely-managed tunnels**: created in the Cloudflare dashboard, run with a single tunnel token
  copied from the “Install and run a connector” panel. **This guide uses this model.**
- **Locally-managed tunnels**: created with `cloudflared login`, use `cert.pem` and config files.
  They are **out of scope** here.

## TL;DR checklist

- Create a remotely-managed tunnel in the Cloudflare dashboard and note its name (for example,
  `dspace-staging-v3`).
- Copy the tunnel token (`eyJ...`) from the **Install and run a connector** panel. Every command on
  that page contains the **same** token.
- On `sugarkube0`, export `CF_TUNNEL_TOKEN` (and optionally `CF_TUNNEL_NAME`), then run
  `just cf-tunnel-install env=<env> token="$CF_TUNNEL_TOKEN"`.
- In the Cloudflare tunnel UI, add a Public hostname routing `staging.democratized.space` to
  `http://traefik.<namespace>.svc.cluster.local:80`.
- Confirm liveness with
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
2. Navigate to **Networks → Cloudflare Tunnels** (or **Connectors → Cloudflare Tunnels**, depending
   on the current UI).
3. Click **Create a tunnel**, choose **Cloudflared** as the connector type, and name the tunnel (for
   example, `dspace-staging-v3`).
4. Click **Save tunnel**. The dashboard shows an **Install and run a connector** panel with
   OS-specific commands. They all embed the **same tunnel token**.

   ```bash
   sudo cloudflared service install <TUNNEL_TOKEN>
   cloudflared tunnel run --token <TUNNEL_TOKEN>
   ```

   The only part Sugarkube needs is `<TUNNEL_TOKEN>` — the long string starting with `eyJ...`. Copy
   it from **any** command on this page; every snippet uses the same token. Do **not** run the
   install scripts on your workstation or Pi; Sugarkube will run `cloudflared` as a container inside
   the cluster.

Refer to Cloudflare’s guide for full details:
[Create a tunnel in the dashboard](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/).

## Step 2 – Run `cloudflared` in the cluster (connector)

This is the “Install and run a connector” step from the Cloudflare UI, but executed by Sugarkube on a
cluster node (for example, `sugarkube0`). The Helm recipe deploys Cloudflare’s **token-only
remotely-managed mode**: the pod sets `TUNNEL_TOKEN` from a Secret and runs
`cloudflared tunnel --no-autoupdate --loglevel debug --metrics 0.0.0.0:2000 run` without any
`cert.pem` or `credentials.json` files.

### Names, environments, and how tunnels are selected

- **Cloudflare tunnel name** (for example, `dspace-staging-v3`): defined in the Cloudflare dashboard
  and tied to the tunnel token you copied.
- **Sugarkube `env`** (for example, `dev`, `staging`): Sugarkube’s environment label. It does **not**
  decide which Cloudflare tunnel you join.
- **CF_TUNNEL_NAME**: optional override so the in-cluster tunnel name matches the Cloudflare
  dashboard name. If omitted, Sugarkube defaults to `sugarkube-<env>`.

The **tunnel token + `CF_TUNNEL_NAME`** decide which Cloudflare tunnel the pod joins. Sugarkube `env`
controls labels and defaults only.

| Sugarkube command | CF_TUNNEL_NAME | Resulting Cloudflare tunnel |
| ----------------- | -------------- | --------------------------- |
| `env=dev`         | `dspace-staging-v3` | Connects to `dspace-staging-v3` |
| `env=staging`     | _(unset)_      | Connects to `sugarkube-staging` (default) |
| `env=dev`         | _(unset)_      | Connects to `sugarkube-dev` (default) |

### Deploy the Helm chart via Sugarkube

Run these commands on `sugarkube0` (or whichever node has your Sugarkube checkout):

1. Point `kubectl` at the cluster and switch to the repo:
   ```bash
   export KUBECONFIG="$HOME/.kube/config"
   cd ~/sugarkube
   ```
2. Export the tunnel token (and optional naming overrides) from the Cloudflare dashboard entry for
   your tunnel. Use the same token shown in the `cloudflared ... --token <TUNNEL_TOKEN>` commands:
   ```bash
   export CF_TUNNEL_TOKEN="eyJ...copy-pasted-from-dashboard..."
   export CF_TUNNEL_NAME="dspace-staging-v3"   # Optional; aligns with the dashboard name
   ```
3. Install or update the chart and Secret on the cluster (namespace is created if needed). Pass the
   token explicitly to keep intent obvious; `env=` refers to Sugarkube’s environment, not a
   Cloudflare concept:
   ```bash
   just cf-tunnel-install env=dev token="$CF_TUNNEL_TOKEN"
   ```
   The recipe strips prefixes like `token=<jwt>` or a full `cloudflared ... --token <jwt>` command
   and stores only the token string in the `tunnel-token` Secret.
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
the canonical way to recover a wedged connector without losing the saved token.

### Worked example: dspace staging tunnel on the `dev` Sugarkube env

This is the literal sequence for deploying the `dspace-staging-v3` tunnel while keeping the
Sugarkube environment set to `dev`:

```bash
# On sugarkube0
export KUBECONFIG="$HOME/.kube/config"
cd ~/sugarkube

# Copy the token from the Cloudflare dashboard (any command on the Install and run a connector page)
# and paste only the long eyJ... string here.
export CF_TUNNEL_TOKEN="<eyJ... token for dspace-staging-v3>"

# Keep names aligned with the Cloudflare dashboard (optional)
export CF_TUNNEL_NAME="dspace-staging-v3"

# Run the installer against the dev Sugarkube environment
just cf-tunnel-install env=dev token="$CF_TUNNEL_TOKEN"

# Sanity check: connector pod should be Ready and liveness should return 200
kubectl -n cloudflare get pods
kubectl -n cloudflare exec deploy/cloudflare-tunnel -- curl -fsS http://localhost:2000/ready
```

Even though the Sugarkube environment is `dev`, this connects the cluster to the
`dspace-staging-v3` tunnel because both the tunnel token and `CF_TUNNEL_NAME` come from that tunnel
in the Cloudflare dashboard. If you prefer matching names, switch `env=dev` to `env=staging` while
keeping the same token and `CF_TUNNEL_NAME` values.

If the pod logs show errors like:

```
Cannot determine default origin certificate path. No file cert.pem ...
error parsing tunnel ID: Error locating origin cert: client didn't specify origincert path
```

`cloudflared` is trying to run in the legacy **locally-managed** mode (expects `cert.pem` or
`TUNNEL_ORIGIN_CERT`) instead of the token-only remotely-managed mode. Common causes:

- The tunnel was originally created as a locally-managed tunnel (with certs) instead of the
  dashboard’s remotely-managed flow.
- The Kubernetes Deployment references a config file or Secret meant for locally-managed tunnels.
- The environment variable or Secret does not contain this tunnel’s token (for example, it contains a
  different API token or a token from another tunnel).

To fix it:

- Double-check that you created the tunnel in the dashboard as described in Step 1 (remotely-
  managed).
- Regenerate or recopy the tunnel token from **Edit tunnel → Install and run a connector**, paste it
  into `CF_TUNNEL_TOKEN`, then run:
  ```bash
  just cf-tunnel-reset
  just cf-tunnel-install env=dev token="$CF_TUNNEL_TOKEN"
  ```
- If in doubt, delete and recreate the tunnel in the dashboard using the remotely-managed flow, then
  update the token in your cluster.

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

- A named Cloudflare Tunnel exists (for example, `dspace-staging-v3`) with a saved tunnel token.
- `cloudflared` runs inside the k3s cluster via `just cf-tunnel-install` using that token.
- A route maps `staging.democratized.space` to
  `http://traefik.<namespace>.svc.cluster.local:80` inside the cluster.
- Cloudflare DNS has (or auto-created) a proxied CNAME pointing `staging.democratized.space` to the
  tunnel’s `*.cfargotunnel.com` name.
- The Sugarkube dspace app expects this persistent tunnel setup to be in place.
