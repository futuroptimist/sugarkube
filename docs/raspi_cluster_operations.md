---
personas:
  - hardware
  - software
---

# Raspberry Pi Cluster Operations

Bring-up via [`raspi_cluster_setup.md`](./raspi_cluster_setup.md) leaves you with a
three-server k3s control plane that already advertises itself over mDNS.
This follow-on guide covers the everyday steps you will take immediately after
`just up <env>` succeeds: validate the cluster, capture reproducible logs, and
install workloads (Helm, token.place, and democratized.space/dspace).

## 1. Confirm the control plane is healthy

1. **Ask k3s for node status** – mirrors the quick check you would normally run
   manually:
   ```bash
   just status
   # == sudo k3s kubectl get nodes -o wide
   ```
2. **Watch pods across all namespaces** to ensure embedded add-ons are healthy:
   ```bash
   sudo k3s kubectl get pods -A -o wide
   ```
3. **Review logs when something looks off.** Sugarkube stores sanitized
   bootstrap transcripts under `logs/up/`, while persistent outage records live
   in [`outages/`](../outages/). Tail `journalctl -u k3s --no-pager` on each
   server if you need to correlate kubelet messages with those saved logs.
4. **Keep the join token handy.** Instead of retyping
   `sudo cat /var/lib/rancher/k3s/server/node-token`, run:
   ```bash
   just cat-node-token env=dev
   ```
   The recipe prints the export command you need for `SUGARKUBE_TOKEN_DEV`
   (or `_INT`, `_PROD`) so you can paste it directly on joining nodes.

## 2. Capture sanitized logs & MDNS diagnostics on demand

`SAVE_DEBUG_LOGS=1` already streams console output through
`scripts/filter_debug_log.py` and writes scrubbed copies to `logs/up/`. Use the
new shortcut when you want that behavior without exporting variables manually:

```bash
just save-logs env=dev
```

Behind the scenes it shells out to the same `just up` recipe, so you still get
the reboot-once memory cgroup patch followed by the cluster join. The helper
prints the sanitized file path at the end (or immediately if you press
<kbd>Ctrl</kbd>+<kbd>C</kbd>). Customize the mDNS redaction allowlist while the
command runs:

```bash
MDNS_ALLOWED_HOSTS="sugarkube0 sugarkube1 lb" just save-logs env=dev
```

The values mirror the environment variable notes that used to live in the setup
guide and prevent unrelated `.local` hostnames from leaking into committed logs.

## 3. Three-server HA loop entirely with Just recipes

You no longer need to remember the `export SUGARKUBE_SERVERS=3` dance. Form and
re-run the HA bootstrap purely with Just:

```bash
# First pass edits cmdline.txt and reboots
just 3ha env=dev

# After SSH reconnects, run it again to bootstrap or join k3s
just 3ha env=dev
```

`just 3ha` simply exports `SUGARKUBE_SERVERS=3` before delegating to the main
`up` target, so the embedded etcd quorum logic is identical to the documented
manual workflow. Pair it with the other helpers when rehearsing:

- `just save-logs env=dev` – capture the sanitized transcript
- `just cat-node-token env=dev` – print the join token export stanza

These shortcuts match the raw commands byte-for-byte, which means the outage
regressions we track in `logs/up/` and `outages/` remain comparable to the
sessions recorded before the helpers existed.

## 4. Improve the cluster before workloads land

Before introducing app traffic, double-check the optional environment settings
that smooth over failovers:

1. **Registration/VIP address:** If kube-vip or an external load balancer fronts
   the control plane, export `SUGARKUBE_API_REGADDR` before running `just 3ha`
   so every node joins via the VIP instead of the leader’s `.local` hostname.
2. **Platform Helm repositories:** The files under [`platform/`](../platform/)
   (for example [`platform/repos.yaml`](../platform/repos.yaml)) show which
   upstream charts Flux or Helmfile will sync once you bootstrap GitOps. Review
   them now so you know which operators (cert-manager, external-dns, Longhorn,
   etc.) will appear automatically.
3. **Time sync + Wi-Fi policies:** Leave `SUGARKUBE_FIX_TIME=1` enabled when you
   expect chrony drifts, and keep `SUGARKUBE_DISABLE_WLAN_DURING_BOOTSTRAP=1`
   whenever Ethernet should be the only control-plane path.

## 5. Install Helm and deploy token.place & dspace

1. **Install Helm (one time per node that manages releases):**
   ```bash
   curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
   helm version
   ```
2. **Add the shared repositories** defined in `platform/repos.yaml` so your CLI
   mirrors what Flux applies:
   ```bash
   helm repo add bitnami https://charts.bitnami.com/bitnami
   helm repo add cloudflare https://cloudflare.github.io/helm-charts
   helm repo update
   ```
3. **Seed namespaces for your apps:**
   ```bash
   kubectl create namespace token-place --dry-run=client -o yaml | kubectl apply -f -
   kubectl create namespace dspace --dry-run=client -o yaml | kubectl apply -f -
   ```
4. **Package and install your projects:**
   - Token.place – the repo already carries Kubernetes manifests in
     [`cluster-rollout-and-migrations.md`](./cluster-rollout-and-migrations.md)
     under the “token.place” track. Wrap those manifests in a chart (for example
     `charts/token-place/values.yaml`) or use Kustomize-to-Helm workflows, then:
     ```bash
     helm upgrade --install token-place charts/token-place \
       --namespace token-place \
       --set image.repository=ghcr.io/futuroptimist/token-place-api
     ```
   - dspace – follow the same pattern, sourcing images from
     [`democratizedspace/dspace`](https://github.com/democratizedspace/dspace).
     The compose-based runbooks ([`pi_token_dspace.md`](./pi_token_dspace.md)
     and [`projects-compose.md`](./projects-compose.md)) document the required
     environment variables; convert them into `values.yaml` entries so Helm can
     inject secrets via Kubernetes resources instead of `.env` files.
5. **Validate the installs:**
   ```bash
   kubectl -n token-place get pods
   kubectl -n dspace get pods
   helm list -A | grep -E 'token-place|dspace'
   ```
6. **Smoke-test the HTTP surfaces** using the bundled sample replay helper:
   ```bash
   just token-place-samples TOKEN_PLACE_SAMPLE_ARGS="--base-url http://token-place.token-place.svc.cluster.local:5000"
   ```

At this point the Pi cluster is no longer a lab toy—it advertises itself via
kube-vip or your chosen VIP, emits auditable logs via `just save-logs`, and runs
Helm-managed workloads that match production (token.place relay/API and the
public dspace front end).
