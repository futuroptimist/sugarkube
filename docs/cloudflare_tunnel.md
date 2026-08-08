# Cloudflare Tunnel (cloudflared) for dspace staging + production rollout

We use **Cloudflare Tunnel** to expose the k3s/Sugarkube cluster to the internet without opening
inbound firewall ports. Canonical dspace hostnames are:

```
https://staging.democratized.space
https://prod.democratized.space
https://democratized.space
```

`prod.democratized.space` is an optional legacy subdomain that now redirects to the apex domain (`democratized.space`).

The tunnel routes these hostnames to Traefik (or another ingress controller) running inside the
k3s cluster. You do **not** need to install or run `cloudflared` on your workstation; the connector
runs inside the cluster.

## WAN outage recovery

### Evidence and lifecycle contract

During the 2026-08-04 staging outage, 16 public probes became unreachable at `01:46:04Z`.
Cloudflare HTTP 530 responses first appeared at `01:56:04Z`, recovery began at `01:59:04Z`, and all
probes had recovered by `02:00:04Z`; the observed 530 phase therefore lasted 120–180 seconds.
“Unreachable” means the probe could not obtain an HTTP response, whereas Cloudflare 530 with error
1033 means Cloudflare could respond but had no healthy connector for the tunnel. See Cloudflare's
[error 1033 explanation](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1033/)
and [tunnel troubleshooting guide](https://developers.cloudflare.com/tunnel/troubleshooting/).

Both connectors failed edge DNS discovery during the WAN/DNS loss. The old Kubernetes liveness
probe called dependency-sensitive `/ready` and, with a failure threshold of one, sent SIGTERM about
11–12 seconds after every start. The clean exits eventually synchronized both pods in Kubernetes'
roughly five-minute restart backoff. Once allowed to restart after connectivity returned, each
connector established four QUIC connections in about three seconds. This proves the delay was not a
multi-minute polling interval: cloudflared already reconnects with its own backoff, but Kubernetes
was preventing the process from remaining alive to do so.

`/ready` on port 2000 is now readiness-only (three failures at ten-second intervals, with a
two-second timeout). There is deliberately no liveness probe: no documented process-local endpoint
has been identified that remains healthy when DNS, WAN, or the Cloudflare edge is unavailable, and
Kubernetes already replaces a container when cloudflared exits. Two replicas retain cross-node
scheduling, rolling updates permit one surge and zero unavailable connectors, and a disruption
budget requires one available connector.

The supported connector is exactly `2026.7.3`, pinned to the multi-architecture manifest digest
`sha256:e39ee8da81ad5e05d77f38d2f51c60ca51bf2a8450ac3abab50c17fdb91d91bf`.
The manifest provides Linux `amd64` and `arm64`, including the cluster's Pi architecture. Never use
`latest`; review Cloudflare's [supported downloads](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/)
before deliberately changing both the tag and verified digest.

### Metrics and alerts

The internal-only `cloudflare-tunnel-metrics` ClusterIP Service gives each connector pod its own
Prometheus target on named port `metrics`. The release-scoped ServiceMonitor scrapes `/metrics`
every 30 seconds with a ten-second timeout. The three staging alerts detect zero aggregate
`cloudflared_tunnel_ha_connections` for five minutes, fewer than the expected eight total
connections for ten minutes, and fewer than two healthy `up` targets for five minutes. Missing
series are explicitly treated as zero. Only sustained critical zero-connection and target-loss
alerts join the existing PagerDuty allowlist; a brief individual QUIC reconnect does not page. See
Cloudflare's [monitoring reference](https://developers.cloudflare.com/tunnel/monitoring/).

### Separately authorized staging rollout and recovery drill

This procedure is manual, post-merge, and **staging only**. It must never run in CI. Before approval,
save `helm -n cloudflare get values cloudflare-tunnel -o yaml` to a secure operator-local temporary
file for rollback; do not commit it. Confirm `just assert-cluster-env staging`, then run
`just cf-tunnel-verify-staging` as a baseline. The verifier fails closed unless it sees one uniquely
owned `cloudflare-tunnel` Helm release. Confirm the existing Secret reference without reading its
value:

```bash
kubectl -n cloudflare get secret tunnel-token -o jsonpath='{.metadata.name}{"\n"}'
helm -n cloudflare list --filter '^cloudflare-tunnel$'
```

After explicit owner authorization, preserve remote-managed ingress and the Secret by reusing the
release's values; do not run the token-creating install recipe for this adoption:

```bash
helm upgrade cloudflare-tunnel cloudflare/cloudflare-tunnel --namespace cloudflare \
  --version 0.3.2 --reuse-values
kubectl -n cloudflare patch deployment cloudflare-tunnel --type=json \
  --patch-file clusters/staging/cloudflare-tunnel/deployment-patch.json
kubectl apply -f clusters/staging/cloudflare-tunnel/service.yaml \
  -f clusters/staging/cloudflare-tunnel/servicemonitor.yaml \
  -f clusters/staging/cloudflare-tunnel/pdb.yaml
kubectl -n cloudflare rollout status deployment/cloudflare-tunnel --timeout=5m
just cf-tunnel-verify-staging
```

Watch the rollout and stop if both old connectors become unavailable; `maxUnavailable: 0` should
keep one connected while the surge pod becomes ready. Verify the pinned image, readiness-only
probe, separate nodes, two Prometheus targets, four HA connections per connector, healthy loaded
rules, and all public staging endpoints with the read-only recipe and the existing public probe
workflow.

For the recovery drill, record both pod UIDs and restart counts, then have the network owner perform
a bounded, owner-scoped staging-only WAN/DNS disruption. Do not delete pods or block Cloudflare
traffic cluster-wide. During the disruption, both pod UIDs and restart counts must remain stable
while readiness becomes false; after cleanup restores the owner's network rule, both pods must
return ready and report at least four HA connections each within the agreed drill window. Run
`just cf-tunnel-verify-staging` again and confirm public probes recover. Cleanup is the removal of
the exact temporary owner-scoped network rule and nothing else.

Abort and roll back if both connectors are unavailable during rollout, a pod restarts because
`/ready` failed, either connector cannot regain four connections, metrics/rules are unhealthy, or
public staging endpoints do not recover. Roll back with `helm -n cloudflare rollback
cloudflare-tunnel <PREVIOUS_REVISION>`, then reapply the operator-local saved values if necessary and
verify the Secret object was not replaced. Because chart 0.3.2 hard-codes the old liveness probe,
rollback restores the known vulnerable lifecycle; use it only to restore service while diagnosing.
The tunnel token and remotely managed hostname routes remain out of band throughout: never print,
rotate, copy into Git, or modify them during rollout or drill.

> Cloudflare has two big modes for tunnels: **remotely-managed** (token-only, created in the
> dashboard) and **locally-managed** (requires `cloudflared login` and a `cert.pem`). Sugarkube uses
> the **remotely-managed, token-based connector mode** only. If you create the tunnel in the
> Cloudflare dashboard as shown below, you are already using the correct mode.

## TL;DR checklist

- Create a remotely-managed tunnel in the Cloudflare dashboard and note its name.
- Copy the tunnel token (`eyJ...`) from the **Install and run a connector** panel.
- On `sugarkube0`, export `CF_TUNNEL_TOKEN` and (optionally) `CF_TUNNEL_NAME`, then run:
  `just cf-tunnel-install env=dev token="$CF_TUNNEL_TOKEN"`.
- In the tunnel UI, configure only the hostnames for **this environment's tunnel**. For example, a
  staging tunnel can route `staging.democratized.space` and `staging.token.place` →
  `http://traefik.<namespace>.svc.cluster.local:80`.
- Confirm readiness: use the port-forward + curl check shown below to hit `/ready` on port 2000.

> `CF_TUNNEL_TOKEN` is only for the Cloudflare Tunnel connector. It is **not** the same credential as the Cloudflare DNS API token used by cert-manager DNS-01 challenges.

One tunnel per cluster/environment can serve many hostnames. For example, the staging tunnel
`dspace-staging-v3` can serve both `staging.democratized.space` and `staging.token.place`, all
routed to Traefik; Traefik then selects the right Kubernetes Ingress by HTTP `Host` header. You can
optionally rename the tunnel later to `sugarkube-staging-v3`, but do not block launch on renaming.

## Prerequisites

- A Cloudflare account.
- Domains for every hostname you plan to publish must be active zones in Cloudflare and use
  Cloudflare nameservers (for example, both `democratized.space` and `token.place` when publishing
  `staging.token.place`).
- `staging.democratized.space`, `prod.democratized.space` (optional legacy redirect host), and
  `democratized.space` (or your preferred rollout hostnames) are managed by Cloudflare DNS.
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
5. Name the tunnel (for example, `dspace-staging-v3`). This can be any unique name and can be reused
   for multiple app hostnames in the same environment.
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

   The only part Sugarkube needs is `<TUNNEL_TOKEN>` – the long connector token (JWT) starting with
   `eyJ...`. You can copy it from **any** of the commands on this page; they all use the same token.
   Copy only the token value, not the whole command.

Refer to Cloudflare’s guide for full details:
[Create a tunnel in the dashboard](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/).

## Step 2 – Run `cloudflared` in the cluster (connector)

This is the “Install and run a connector” step from the Cloudflare UI. It must run on a node in the
k3s cluster (for example, `sugarkube0`), **not** on your workstation. `just cf-tunnel-install` is
the canonical way to install the connector on the Pi. The recipe deploys Cloudflare’s **token-based
connector mode**: the pod sets `TUNNEL_TOKEN` from the `tunnel-token` Secret and runs `cloudflared tunnel --no-autoupdate run --token "$TUNNEL_TOKEN"`
(plus metrics flags) with **no** `cert.pem` or `credentials.json`.

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

   The pinned `cloudflare/cloudflared:2026.7.3` image is minimal and does **not** ship `curl`, so
   `kubectl exec ... curl ...` fails with `executable file not found in $PATH`. Kubernetes already
   probes `http://localhost:2000/ready`, so manual checks are optional. If you want to confirm the
   connector yourself, use a two-shell port-forward from `sugarkube0` (or any node with `kubectl`
   access) and keep Shell 1 running while you run Shell 2. Start by confirming the Deployment is
   up:

   ```bash
   kubectl -n cloudflare get deploy,po -l app.kubernetes.io/name=cloudflare-tunnel
   ```

   Then use a two-shell port-forward to reach the readiness endpoint:

   **Shell 1 – port-forward the metrics/ready port (keep this command running):**

   ```bash
   kubectl -n cloudflare port-forward deploy/cloudflare-tunnel 2000:2000
   ```

   **Shell 2 – call `/ready` from the host while Shell 1 is active:**

   ```bash
   curl -fsS http://localhost:2000/ready
   ```

   A JSON response with `"status":200` (for example,
   `{"status":200,"readyConnections":4,"connectorId":"..."}`) indicates the tunnel is healthy.
   In normal operation the Kubernetes readiness probe and the Cloudflare dashboard “Connected” state
   are sufficient; this port-forward check is just an extra manual confirmation.

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

# Optional manual readiness check (two shells)
# Shell 1 (keep running):
kubectl -n cloudflare port-forward deploy/cloudflare-tunnel 2000:2000
# Shell 2:
curl -fsS http://localhost:2000/ready
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
requests to your mapped hostnames (for example `staging.democratized.space`,
`staging.token.place`, optional `prod.democratized.space` redirect host, and `democratized.space`)
reach Traefik.

### If an app client sees HTTP 403 before the app logs it

For token.place desktop compute-node registration, staging showed a useful split-brain symptom:
synthetic curl against `/api/v1/relay/servers/register` and `/api/v1/relay/servers/poll` succeeded,
but the desktop client received HTTP 403 and relay logs did not show matching POSTs. Treat that as
a Cloudflare/pre-app rejection until proven otherwise.

Triage sequence:

1. Capture the failing client timestamp, hostname, path, response status, and `cf-ray` response
   header.
2. Check the application logs for a matching POST. For token.place:

   ```bash
   kubectl -n tokenplace logs deploy/tokenplace --since=30m --tail=500 | \
     grep -E 'api/v1/relay/servers/(register|poll)|server\.(registered|reregister|heartbeat)'
   ```

3. If the app logs are silent, open **Cloudflare Security Events** and search by `cf-ray`, client IP,
   hostname, path, and user agent to find the WAF, bot, access, or firewall rule that generated the
   403.
4. Compare a successful synthetic curl with the failing desktop request: method, URL path, host,
   `Content-Type`, `User-Agent`, `Origin`, auth headers, and whether the desktop is sending extra
   headers that match a Cloudflare rule.
5. Keep Cloudflare credentials distinct: `CF_TUNNEL_TOKEN` is the connector token for the tunnel
   pod, while the Cloudflare DNS API token is used by cert-manager DNS-01. Neither one is the
   token.place relay server registration token.

If a matching app log exists, debug the application response. If no app log exists and Cloudflare
has a Security Event for the same `cf-ray`, fix the Cloudflare rule or client headers before
changing Kubernetes or token.place code.

### Recovery and reset

If rollout gets stuck (CrashLoopBackOff, old ReplicaSets, etc.), use the built-in teardown helpers to
return to a clean token-mode state:

- Inspect status and logs:

  ```bash
  just cf-tunnel-debug
  ```

  In `cf-tunnel-debug` logs, look for `Updated to new configuration` and confirm your target
  hostname appears. If the tunnel is connected but the Kubernetes app ingress is not created yet,
  a `404` is expected until that ingress exists.

- If logs warn that the cloudflared image is outdated, treat that as a separate maintenance item.
  Do not block app deployment when the tunnel is connected and hostname routes work.

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

## Step 3 – Publish application routes for one environment tunnel

Now that the connector is running in the cluster, configure routes for the hostnames that belong to
this tunnel/environment and point them to the internal Traefik Service.

1. In the tunnel configuration, open the **Public hostnames**, **Application routes**, or
   **Published applications** section.
2. Add routes/applications (example for staging tunnel):
   - **Hostname**: `staging.democratized.space`
   - **Hostname**: `staging.token.place`
   - **Service type**: `HTTP`
   - **Service URL**: `http://traefik.<namespace>.svc.cluster.local:80`

   Replace `<namespace>` with the namespace used by your ingress controller inside the k3s cluster.
   For production, use a separate production tunnel and publish production hostnames there (for
   example, `democratized.space` and optional legacy `prod.democratized.space` redirect host).
3. Save the routes. This sends HTTPS traffic for each hostname through the tunnel into the Traefik
   ClusterIP service in your k3s cluster.

See Cloudflare’s docs for the latest UI steps:
[Publish an application through Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/#publish-an-application).

## Step 4 – Verify / create DNS records for published hostnames

The hostnames you published (for example, `staging.democratized.space` and `staging.token.place` for
staging) must be managed by Cloudflare DNS in their respective zones. When you publish hostnames
through the tunnel UI, Cloudflare **usually** creates proxied CNAMEs automatically that point each
hostname to your tunnel’s
`*.cfargotunnel.com` address.

If you see DNS records for the rollout hostnames pointing at `<UUID>.cfargotunnel.com`, you’re done.

### Manual creation (fallback)

Only create this manually if the CNAME is missing:

1. Go to **Cloudflare dashboard → DNS → Records** for each relevant zone (for example,
   `democratized.space` and `token.place`).
2. Click **Add record**.
3. Configure records as needed in each zone:
   - **Type**: `CNAME`
   - **Name**: hostname label for that zone (for example, `staging` in either zone, `prod`, or `@`
     for apex)
   - **Target**: `<UUID>.cfargotunnel.com` (the tunnel hostname shown in the dashboard)
   - **Proxy status**: **Proxied** (orange cloud)
4. Save the record.

## Step 5 – Keep `prod.` as an optional redirect host

`prod.democratized.space` is now used as an optional redirect host. Keep (or convert) it as a
simple redirect (Cloudflare Redirect Rule or Page Rule) to avoid maintaining duplicate origins:

- **Source**: `https://prod.democratized.space/*`
- **Target**: `https://democratized.space/$1`
- **Status code**: `301` (permanent) once confident, or `302` during transition.

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

- A named Cloudflare Tunnel exists (for example, `dspace-staging`) with a saved token.
- `cloudflared` runs inside the k3s cluster via `just cf-tunnel-install` using that token.
- Routes for a given environment tunnel map that environment’s hostnames (for example,
  `staging.democratized.space` and `staging.token.place`) to
  `http://traefik.<namespace>.svc.cluster.local:80` inside the cluster.
- Cloudflare DNS has (or auto-created) proxied records in each required zone (for example,
  `democratized.space` and `token.place`) pointing published hostnames to the tunnel’s
  `*.cfargotunnel.com` name.
- After apex promotion, `prod.democratized.space` can be converted to a redirect to
  `https://democratized.space`.
- The Sugarkube dspace app expects this persistent tunnel setup to be in place.
