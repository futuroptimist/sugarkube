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

   The `cloudflare/cloudflared:2026.7.3` image is minimal and does **not** ship `curl`, so
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


## WAN/DNS outage recovery contract

### Evidence and root cause

During the staging incident on 2026-08-04, 16 public probes became unreachable at
`01:46:04Z`. The first Cloudflare HTTP 530 responses appeared at `01:56:04Z`, recovery began at
`01:59:04Z`, and every probe had recovered by `02:00:04Z`; the observed 530 phase lasted 120–180
seconds. An unreachable probe means no HTTP response reached the observer. By contrast, Cloudflare
HTTP 530 with error 1033 means Cloudflare answered but had no healthy connector connected to the
edge. See Cloudflare's [error 1033 explanation](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1033/)
and [Tunnel troubleshooting guide](https://developers.cloudflare.com/tunnel/troubleshooting/).

Both connectors failed edge DNS discovery during the WAN/DNS outage. The old Kubernetes liveness
probe called `/ready`, an endpoint which depends on an active edge connection, and killed each pod
about 11–12 seconds after it started. Their synchronized clean exits eventually produced roughly
five-minute Kubernetes restart backoffs. After WAN/DNS recovery and a restart, each connector
registered four QUIC connections in about three seconds. The delay was therefore **not** a
multi-minute polling interval: cloudflared already reconnects with backoff, but Kubernetes prevented
it from staying alive long enough to do so.

`/ready` on port 2000 is now readiness-only (10-second period, two-second timeout, three failures).
A disconnected connector is removed from readiness without being killed. There is deliberately no
liveness probe: no documented process-local endpoint in this chart remains healthy independently of
WAN, DNS, and edge availability, and Kubernetes restarts the container if cloudflared exits. Two
replicas use required hostname anti-affinity, rolling updates use `maxUnavailable: 0` and
`maxSurge: 1`, and a disruption budget keeps at least one connector available.

### Supported version, metrics, and alerts

The staging connector is pinned to `cloudflare/cloudflared:2026.7.3` and the verified multi-platform
manifest digest. The manifest contains Linux `amd64` and `arm64` images, matching development and
Pi cluster needs. Never substitute `latest`; review the [official downloads and supported-version
page](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/)
before updating both tag and verified digest. Chart `cloudflare-tunnel-0.3.2` does not expose a
digest value, so the canonical install recipe applies the immutable `tag@digest` to the chart-owned
Deployment without changing the chart version.

The private `cloudflare-tunnel-metrics` ClusterIP Service selects only the two release pods. Its
ServiceMonitor is discovered by `kube-prometheus-stack` and scrapes each pod as a distinct target at
`/metrics` every 30 seconds with a 10-second timeout. Nothing exposes port 2000 publicly. Cloudflare
documents these [connector metrics and readiness semantics](https://developers.cloudflare.com/tunnel/monitoring/).

### Alerts

- `CloudflareTunnelNoHealthyConnections` pages after aggregate
  `cloudflared_tunnel_ha_connections` remains zero for five minutes when at least one connection series is present. Missing connection
  metrics do not prove an outage.
- `CloudflareTunnelConnectionsDegraded` warns after ten minutes if fewer than two connector series
  exist or either connector reports fewer than the expected four HA connections. This delay excludes
  ordinary rolling churn and brief individual QUIC reconnections.
- `CloudflareTunnelMetricsTargetsDown` warns after five minutes if `up` shows fewer than two healthy
  targets, including absent series. Missing telemetry does not by itself prove tunnel failure.

Run the repository-owned, read-only gate only against staging:

```bash
just cf-tunnel-verify env=staging
```

It fails closed on the context, chart/release ownership, image, probes, HA scheduling and rollout,
Secret **reference**, Service/ServiceMonitor selectors, two Prometheus targets, HA connection counts,
and loaded/non-firing alerts. It never reads Secret data.

### Separately authorized post-merge rollout and recovery drill

This procedure is manual, staging-only, and must never run in CI. Obtain owner authorization and a
maintenance window before starting. The live `cloudflare/cloudflare-tunnel` Helm release installed
by `just cf-tunnel-install` is the intended reconciliation path. The dormant `platform/cloudflared`
Flux resources use a different namespace and credential contract; do not reconcile or adopt them as
part of this rollout.

1. Select staging and prove ownership before mutation:

   ```bash
   just assert-cluster-env env=staging
   test "$(kubectl config current-context)" = sugar-staging
   helm -n cloudflare list --filter '^cloudflare-tunnel$'
   kubectl -n cloudflare get deploy cloudflare-tunnel -o jsonpath='{.metadata.labels.app\.kubernetes\.io/managed-by}{"\n"}'
   kubectl -n cloudflare get secret tunnel-token -o name
   ```

   Stop unless exactly one deployed `cloudflare-tunnel` release exists and the Deployment is
   Helm-managed. Do not print, replace, rotate, or recreate the existing Secret. Remote-managed host
   routes stay in Cloudflare and are not part of this repository rollout.

2. Record `helm -n cloudflare history cloudflare-tunnel`, the current revision, public endpoint
   results, pod/node placement, and image. The preflight-confirmed Secret is preserved: supply no
   token argument or `CF_TUNNEL_TOKEN` value, and do not read, print, or reapply the token. Run
   `just cf-tunnel-install env=staging`. Watch
   `kubectl -n cloudflare rollout status deploy/cloudflare-tunnel --timeout=5m` and confirm at every
   transition that at least one old or new pod remains Ready.
3. Run `just cf-tunnel-verify env=staging`; verify two Ready pods on separate nodes, version
   `2026.7.3`, readiness-only `/ready`, two Prometheus targets, four HA connections per connector,
   healthy alerts, and every approved staging public endpoint.
4. A pod-deletion drill is not an acceptable WAN-recovery test: it proves replacement, not that the
   same cloudflared processes stay alive during dependency loss and reconnect afterward.

   A deny-egress `NetworkPolicy` created after cloudflared has connected is not an acceptable substitute.
   Kubernetes explicitly makes the effect of a newly applied policy on existing connections
   [implementation-defined](https://kubernetes.io/docs/concepts/services-networking/network-policies/#network-traffic-filtering),
   so a conforming implementation can leave established QUIC sessions intact. On 2026-08-09 the uniquely
   owned staging policy `cloudflare-wan-drill-20260809t060056z-29424` selected both connectors, but both
   remained Ready through 23 polls over about 120 seconds. That result is an **inconclusive dependency-loss
   test**, not a pass: cleanup removed the exact policy, the original UIDs and restart counts were
   unchanged, all four HA connections per pod returned healthy, no alert fired, and all 16 public probes
   remained HTTP 200. Operator evidence remains local and must not be committed.

5. Use `just cf-tunnel-wan-dependency-loss-drill env=staging` to print the repository-owned,
   non-mutating plan. The deterministic mechanism is an nftables output-hook table inside each exact pod
   network namespace which drops TCP and UDP edge traffic on ports 443 and 7844. Unlike a post-connection
   NetworkPolicy, a netfilter output hook sees packets from established QUIC flows; it leaves the
   cloudflared processes and local readiness/metrics traffic running. It never adds a host-wide rule or
   flushes a ruleset. Execution remains **blocked** unless every preflight succeeds, an approved revision
   and authenticated node executor are explicitly supplied, and the operator types the exact confirmation.

   Before either drop table is installed, the helper resolves the exact CRI pod sandbox PID and installs
   an independently surviving, four-minute transient systemd cleanup timer on both nodes. Each table name
   contains the bounded unique owner ID and sandbox PID. Cleanup deletes only those exact tables and prints
   exact per-node manual cleanup commands if deletion cannot be proved. The runner must provide already
   authorized, host-key-verified access; the helper never creates keys, handles interactive credentials,
   weakens SSH host checking, or assumes unattended access. If such execution is unavailable, it refuses
   the live drill.

   An authorized run must pass `--execute`, set `CF_WAN_APPROVED_REVISION` to the reviewed commit and
   `CF_WAN_NODE_EXEC` to the approved runner, and pass
   `--confirm 'INTERRUPT BOTH STAGING CLOUDFLARE CONNECTORS'`. It captures only sanitized Kubernetes,
   Helm, metrics and endpoint evidence under `~/operator-evidence`; it never requests Secret values. It
   proves both original pods become NotReady with zero HA connections and no restart, removes the exact
   tables, then proves those same UIDs recover Ready with at least four HA connections within five minutes.
   It also requires endpoint, Helm history, Secret metadata, Deployment, and the full read-only verifier
   to remain healthy. Do not execute this procedure in CI or without separate owner authorization.
6. Cleanup is `unset CF_TUNNEL_TOKEN CF_TUNNEL_NAME CF_TUNNEL_ID`; retain the two healthy pods,
   Service, ServiceMonitor, and PDB.

Rollback immediately if no connector stays Ready, a public endpoint fails for two consecutive
one-minute checks, a replacement does not reach four HA connections within five minutes, metrics
remain below two healthy targets, or a new critical alert fires. Use
`helm -n cloudflare rollback cloudflare-tunnel <recorded-revision> --wait --timeout 5m`, then restore
the repository-owned monitoring manifest if needed and re-run the public checks. Because Helm 0.3.2
does not retain the post-install lifecycle patch in an older revision, rollback is an emergency
availability action; do not delete or alter `tunnel-token`, and stop for owner review before any
further rollout.

The connector token remains out of band. It is never stored in Git, metrics, test fixtures, operator
captures, or commands that print its value.
