---
personas:
  - hardware
  - software
---

# Raspberry Pi Cluster Operations & Helm Workloads

**📚 Part 3 of 3** in the [Raspberry Pi cluster series](index.md#raspberry-pi-cluster-series)
- **Previous:** [Part 2 - Quick-Start Setup](raspi_cluster_setup.md)
- **See also:** [Part 1 - Manual Setup](raspi_cluster_setup_manual.md)
- **Manual companion:** [Raspberry Pi Cluster Operations (Manual)](raspi_cluster_operations_manual.md)

`raspi_cluster_setup.md` gets every Raspberry Pi onto the same HA k3s control plane.
This follow-up guide covers the day-two routine: checking cluster health, capturing
logs, preparing Helm, and rolling out real workloads like
[token.place](https://github.com/futuroptimist/token.place) and
[democratized.space (dspace)](https://github.com/democratizedspace/dspace).

> **Note**
> If you've copied the k3s kubeconfig to `/home/pi/.kube/config` and set
> `KUBECONFIG=$HOME/.kube/config` for the `pi` user (see the setup guide), you can omit `sudo`
> from the `kubectl` examples in this guide when running them on the Pis.

> **Prerequisite**
> Complete the 3-server quick-start in [raspi_cluster_setup.md](./raspi_cluster_setup.md)
> so every Pi already shares the same token and environment.

## In this guide you will:

- Verify the health of your three-node HA control plane
- Capture and commit sanitized bring-up logs for debugging and documentation
- Install Helm and deploy the token.place workload
- Deploy the democratized.space (dspace) application
- Hook your cluster into Flux for GitOps-managed releases
- Learn operational recipes for day-to-day cluster management

## Golden path: HA dev cluster → Helm → Traefik → workloads

Follow this sequence after imaging and booting the Pis:

1. **Form or re-run the HA cluster:** From each node, use the quick-start flow in
   [raspi_cluster_setup.md](./raspi_cluster_setup.md) and verify:

   ```bash
   just ha3 env=dev
   just cluster-status
   ```

2. **Install Helm (required before any Helm chart installs):**

   ```bash
   just helm-install
   just helm-status
   ```

3. **Inspect Gateway API CRDs:** Missing CRDs or a fully healthy set are both OK; the Traefik doctor
   only fails on problematic ownership and prints remediation steps.

   ```bash
   just traefik-crd-doctor
   ```

4. **Install and verify Traefik ingress:**

   ```bash
   just traefik-install
   just traefik-status
   ```

5. **Deploy workloads:** Continue with the workload sections in this guide (for example,
   [token.place](./pi_token_dspace.md) or [dspace](https://github.com/democratizedspace/dspace)) once
   ingress is healthy.

## Install Helm (prerequisite for Traefik and Helm workloads)

Helm simplifies Kubernetes application deployment by packaging manifests, providing templating, and
managing releases. Rather than applying dozens of YAML files manually, Helm charts let you install
and upgrade applications with a single command.

First, ensure Helm is installed. The Sugarkube Pi image includes Helm by default, but if you're
working with a minimal OS, use the `just` recipes from the repository root:

1. Install (or detect) Helm:

   ```bash
   just helm-install
   ```

   This detects whether Helm is already present. If missing, it installs Helm 3 using the official
   `get-helm-3` script and prints the installed version on success.

2. Verify Helm is working:

   ```bash
   just helm-status
   ```

   This prints the Helm version and fails if Helm is not installed correctly.

If you prefer to install Helm manually or are unable to use the `just` recipes, see the manual
operations guide: `docs/raspi_cluster_operations_manual.md#1-install-helm-manually`.

### Authenticate Helm with OCI registries (GHCR for dspace)

Sugarkube's Helm helpers (for example, `just helm-oci-install`) and newer workload docs assume you
can pull charts directly from OCI registries such as `ghcr.io`. GitHub Container Registry (GHCR)
requires an authenticated bearer token even for public Helm charts. Skipping authentication leads
to errors like:

```text
Error: failed to perform "FetchReference" on source:
  GET "https://ghcr.io/v2/democratizedspace/charts/dspace/manifests/3.0.0":
  GET "https://ghcr.io/token?scope=repository%3Ademocratizedspace%2Fcharts%2Fdspace%3Apull&service=ghcr.io":
  response status code 401: unauthorized: authentication required
```

Authenticate once per node that will pull OCI charts:

```bash
# 1) Create a GitHub Personal Access Token with the `read:packages` scope.
# 2) Then, on each node that will pull OCI charts:

export GHCR_USERNAME="your_github_username"
export GHCR_PAT="your_pat_with_read_packages"

echo "${GHCR_PAT}" | helm registry login ghcr.io \
  --username "${GHCR_USERNAME}" \
  --password-stdin
```

Safety tips:

- Never commit the PAT to Git. Store the exports in a root-owned file outside the repo or in a
  private shell profile.
- Re-run the login on each node if the PAT rotates or you rebuild the cluster.

Why this matters for dspace:

- The dspace Helm chart is published at `oci://ghcr.io/democratizedspace/charts/dspace` with
  semantic versions such as `3.0.0`.
- Commands like `helm pull oci://ghcr.io/democratizedspace/charts/dspace --version 3.0.0` and
  `just helm-oci-install ... chart=oci://ghcr.io/democratizedspace/charts/dspace ...` require the
  GHCR login above.
- Once Helm and GHCR login are working, higher-level recipes such as `just helm-oci-install` can
  be used for OCI-hosted workloads (see the workload-specific docs for full examples).

Common errors:

- **401 / `authentication required`:** Run `helm registry login ghcr.io` with a PAT that has the
  `read:packages` scope.
- **`...:3.0.0: not found`:** The requested chart version is absent—check the version documented in
  the dspace repo (for example, `docs/apps/dspace.version`) and pull that version instead.

## Install and verify Traefik ingress

> This section expands step 4 of the golden path above (installing and validating Traefik).

Sugarkube clusters expect a Kubernetes ingress controller to route HTTP(S) traffic into your
services. The docs and examples in this repo assume [Traefik](https://traefik.io/) as the default
ingress controller. Other controllers can work, but this guide only documents the Traefik path.

Run the helper recipe as your normal user (e.g., `pi`), not with `sudo`:

```bash
just traefik-install
```

What this does:

- Repairs `$HOME/.kube/config` from `/etc/rancher/k3s/k3s.yaml` when needed so Helm and kubectl use a
  user-owned kubeconfig.
- Runs a Gateway API CRD ownership check (via `traefik-crd-doctor`) and fails fast if existing CRDs
  are owned by something other than Traefik in `kube-system`.
- Installs or upgrades the Traefik Helm release (`traefik/traefik`) in `kube-system` with
  `helm upgrade --install ... --wait --timeout=5m`, explicitly enabling Gateway API CRDs.
- Verifies the `traefik` Service exists and prints quick troubleshooting hints if it does not.

Verify the install with any of the following:

```bash
kubectl -n kube-system get pods -l app.kubernetes.io/name=traefik
kubectl -n kube-system get svc -l app.kubernetes.io/name=traefik
just traefik-status
```

Re-run `just traefik-install` any time; it is idempotent and safe to use after fixing kubeconfig,
taints, or CRD ownership. If Helm is missing, the recipe exits with a pointer to
`docs/raspi_cluster_operations_manual.md#1-install-helm-manually`.

**Gateway API CRDs and Helm ownership**

Traefik's Gateway API CRDs must be managed by Helm. The recipe uses the CRD doctor to confirm that
any existing CRDs are owned by a Traefik release in `kube-system`. Missing CRDs are acceptable—the
main `traefik/traefik` chart will create them—and already healthy, Traefik-owned CRDs are also fine.
If `just traefik-install` reports ownership problems, run the doctor before retrying the install.

### Traefik Gateway API CRD doctor (`just traefik-crd-doctor`)

This helper inspects the Gateway API CRDs and their Helm metadata, reports whether Traefik can
safely manage them, and prints the exact `kubectl` commands to fix conflicts. It defaults to a
read-only dry-run; destructive changes require the explicit `apply=1` flag and user confirmation.

Run it any time you see Traefik CRD ownership errors:

```bash
just traefik-crd-doctor
```

For non-default namespaces, pass the `namespace` argument:

```bash
just traefik-crd-doctor namespace=my-other-namespace
```

If the doctor reports no problematic CRDs with either all CRDs **missing** or all CRDs **healthy**, you
are good to proceed—Traefik will create missing CRDs during install or already owns the healthy set.
Only the problematic states require action; follow the recommended commands the doctor prints.

Example outputs:

- Clean Traefik ownership:

  ```text
  === Gateway API CRD ownership check (expected release namespace: kube-system) ===
  ✅ gatewayclasses.gateway.networking.k8s.io: owned by release traefik in namespace kube-system (OK)
  ```

- Missing CRDs (safe for Traefik to create):

  ```text
  ✅ httproutes.gateway.networking.k8s.io: missing (will be created by the Traefik chart if enabled)

  No problematic Gateway API CRDs detected. All expected CRDs are missing; the Traefik chart can create them when installed.
  Next step: run 'just traefik-install' to install Traefik and let it create the CRDs.
  ```

- Unmanaged CRDs (no Helm ownership metadata; Traefik will adopt them):

  ```text
  ✅ gateways.gateway.networking.k8s.io: present without Helm ownership metadata (will adopt into Traefik release)

  No problematic Gateway API CRDs detected. Existing CRDs are present without Helm ownership metadata; Traefik can adopt them into its release.
  Traefik will add Helm labels/annotations and take ownership of these CRDs during install.
  ```

- Problematic CRDs installed by something else:

  ```text
  ⚠️  gateways.gateway.networking.k8s.io: managed-by=, release-name=other-release, release-namespace=default (expected Traefik Helm in kube-system)
  Recommended actions:
    1) Delete and let Traefik recreate (fresh clusters):
       kubectl delete crd gateways.gateway.networking.k8s.io

    2) Patch to mark Helm ownership (advanced):
       kubectl label crd <name> app.kubernetes.io/managed-by=Helm --overwrite
       kubectl annotate crd <name> \
         meta.helm.sh/release-name=traefik \
         meta.helm.sh/release-namespace=kube-system --overwrite
  ```

Suggested remediation commands:

- **Delete and recreate (recommended for fresh homelab clusters):**

  ```bash
  kubectl delete crd \
    backendtlspolicies.gateway.networking.k8s.io \
    gatewayclasses.gateway.networking.k8s.io \
    gateways.gateway.networking.k8s.io \
    grpcroutes.gateway.networking.k8s.io \
    httproutes.gateway.networking.k8s.io \
    referencegrants.gateway.networking.k8s.io
  ```

- **Patch for Helm adoption (advanced):**

  ```bash
  for crd in gatewayclasses.gateway.networking.k8s.io httproutes.gateway.networking.k8s.io; do
    kubectl label crd "${crd}" app.kubernetes.io/managed-by=Helm --overwrite
    kubectl annotate crd "${crd}" \
      meta.helm.sh/release-name=traefik \
      meta.helm.sh/release-namespace=kube-system --overwrite
  done
  ```

  Replace the CRD names with the full list if you prefer patching over deletion.

After deleting or patching the CRDs, re-run `just traefik-crd-doctor` until no problematic CRDs
remain, then re-run `just traefik-install` to complete the installation.

> ⚠️ **Dangerous foot-gun: `apply` mode**
>
> `just traefik-crd-doctor apply=1` will run destructive `kubectl delete` commands against
> cluster-wide Gateway API CRDs. Only use this on a fresh homelab cluster where you are sure nothing
> else depends on Gateway API. By default the doctor is read-only and is the recommended way to
> diagnose issues.

> **Next step:** With ingress healthy, continue to the workload sections (token.place, dspace, or your
> own apps) later in this guide so Traefik can route external traffic.

## Using control-plane nodes as workers (homelab mode)

In this project’s default Raspberry Pi homelab topology, we run a three-node HA k3s control
plane (sugarkube0/1/2) and also use those nodes for workloads (web apps and APIs).

By default, k3s taints control-plane nodes with:

```bash
node-role.kubernetes.io/control-plane:NoSchedule
```

This prevents normal workloads (including Traefik) from being scheduled on those nodes and
leads to events like:

```text
0/3 nodes are available: 3 node(s) had untolerated taint {node-role.kubernetes.io/control-plane: true}.
```

To treat all three nodes as schedulable workers in your homelab cluster, run:

```bash
just ha3-untaint-control-plane
```

This command:

- Lists all nodes in the cluster.
- Removes the `node-role.kubernetes.io/control-plane:NoSchedule` and
  `node-role.kubernetes.io/master:NoSchedule` taints where present.
- Leaves nodes without those taints unchanged and shows the resulting taint state.

Before installing Traefik on the ha3 topology, run this helper so the three control-plane nodes
can schedule the Traefik pods and the k3s klipper-helm jobs that bootstrap the addon.

This command expects kubectl to be configured for the cluster (for example, using
`~/.kube/config`). If kubectl cannot reach the API server, it prints a clear error and exits
instead of surfacing low-level client errors.

After running it, all nodes become eligible to run workloads like Traefik and your apps. This is
appropriate for a low-traffic, non-commercial homelab cluster. If you later add dedicated worker
nodes and want a stricter separation, you can reapply taints or avoid running this helper.

## Check cluster, Helm, and Traefik status

When you want a quick health dashboard, run the high-level status recipe:

```bash
just cluster-status
```

This read-only command prints:

- Cluster nodes via `kubectl get nodes -o wide`
- Helm availability on the node (version and `which helm`)
- Traefik pods and services in `kube-system`
- Any ingress classes configured in the cluster

Example (abbreviated) output:

```text
=== Cluster nodes (kubectl get nodes) ===
ip-10-0-0-1   Ready    control-plane,etcd   v1.28.7+k3s1   10.0.0.1   ...

=== Helm status (CLI on this node) ===
v3.13.0+gXXXXXXXX
```

If `kubectl` cannot reach the cluster (for example, kubeconfig is not set yet), the command
will say so and skip the Kubernetes-dependent checks instead of showing low-level client
errors. In that case, run `kubectl version` or `kubectl get nodes` directly and fix your
kubeconfig or server connectivity before relying on `just cluster-status`.

This is a convenient health dashboard to confirm your 3-node HA cluster is up, Helm is available,
and Traefik is installed before deploying apps like dspace. For the underlying `kubectl` and
`helm` commands that this wraps, see the manual operations guide:
`docs/raspi_cluster_operations_manual.md`.

## Deploy your first app (generic ingress path)

If you want a fast path to your first live app, follow this numbered tutorial.
It assumes your `env=dev` cluster is online and reachable with kubectl and that
Traefik is installed per the section above.

1. Install Cloudflare Tunnel on a node that can reach the cluster API (see
   [Cloudflare Tunnel docs](cloudflare_tunnel.md)):

   ```bash
   just cf-tunnel-install env=dev token=$CF_TUNNEL_TOKEN
   ```

2. Create a Tunnel route in the Cloudflare dashboard from your chosen FQDN to
   `http://traefik.kube-system.svc.cluster.local:80`. Cluster DNS makes the
   `traefik.kube-system.svc.cluster.local` hostname resolvable from every node,
   so the tunnel can reach Traefik reliably.

3. Install your app using its Helm or `just` recipe. For example, the
   [dspace app guide](apps/dspace.md) shows how to deploy dspace v3 with a
   Traefik ingress host and tested values.

4. Verify everything is healthy, then browse to the FQDN on your phone or
   laptop:

   ```bash
   kubectl -n <app-namespace> get ingress,pods,svc
   ```

5. Iterate new builds using your app's upgrade instructions (e.g., the dspace
   guide covers rolling new `v3-<shortsha>` images).

## Step 1: Verify your 3-node control plane is healthy

After completing the cluster setup from `raspi_cluster_setup.md`, you should have
three nodes ready to run workloads. This step confirms that your control plane is
stable and all nodes are communicating properly.

### Why verify cluster health?

Before deploying applications, you need to ensure that all three nodes in your HA
control plane are ready, etcd is healthy, and the Kubernetes API server is
responding correctly. This baseline check catches configuration issues early.

Run the following commands to check cluster status:

```bash
just status
```

**What you should see:** Output similar to `kubectl get nodes -o wide` showing all
three nodes in the `Ready` state with their IP addresses, OS versions, and kubelet
versions. The `just status` recipe guards against running before k3s exists and
prints a helpful reminder if the control plane is missing.

For continuous monitoring while waiting for the third HA node to report `Ready`:

```bash
watch -n5 kubectl get nodes
```

You can also set up kubectl access from your workstation by copying the kubeconfig:

```bash
just kubeconfig env=dev
```

**What you should see:** This creates `~/.kube/config` with the context renamed to
`sugar-dev`, allowing you to run kubectl commands from your local machine.

Verify workloads across all namespaces:

```bash
kubectl get pods -A
```

**What you should see:** System pods (like `coredns`, `traefik`, and `metrics-server`)
in the `kube-system` namespace, all showing `Running` status. If any pods are in
`Pending` or `CrashLoopBackOff` states, investigate using:

```bash
kubectl describe node <name>
```

This command inspects taints, kubelet configuration, and resource pressure that
might prevent pods from scheduling.

### Operational commands cheat sheet

Quick reference for the most common recipes when operating your cluster:

| Recipe | What it does | When to use |
|--------|--------------|-------------|
| `just status` | Display cluster nodes with `kubectl get nodes -o wide` | Check overall cluster health and node readiness. Guards against running before k3s is installed. |
| `just kubeconfig env=dev` | Copy k3s kubeconfig to `~/.kube/config` with context renamed to `sugar-dev` | Set up kubectl access from your workstation or after re-imaging a node. |
| `just save-logs env=dev` | Run cluster bring-up with `SAVE_DEBUG_LOGS=1` into `logs/up/` | Capture sanitized logs for troubleshooting, documenting cluster changes, or sharing with the community. |
| `just cat-node-token` | Print the k3s node token for joining nodes | Retrieve the token when adding new nodes or switching to a different shell session. |
| `just wipe` | Clean up k3s and mDNS state on a node | Recover from a failed bootstrap/join or remove a node that joined the wrong cluster. Re-run `just ha3 env=dev` afterward. |
| `just dspace-debug-logs` | Dump dspace and Traefik logs for the last 200 lines each | Investigating 500s or routing issues for dspace. |

## Step 2: Capture and commit sanitized bring-up logs

Capturing logs from your cluster bring-up process creates a valuable record for
troubleshooting, documentation, and sharing with the community. Sugarkube includes
a log sanitizer that removes sensitive information automatically.

### Why capture logs?

Sanitized logs help you debug issues, document your setup process, and contribute
examples back to the project. The log filter removes IP addresses, MAC addresses,
and other potentially sensitive data while preserving the operational narrative.

To capture logs during cluster setup, use the `just save-logs` recipe:

```bash
just save-logs env=dev
```

This is equivalent to running:

```bash
SAVE_DEBUG_LOGS=1 just up dev
unset SAVE_DEBUG_LOGS  # stop logging in this shell
```

**What you should see:** Console output streams normally, but a sanitized copy is
written to `logs/up/` with a timestamp, commit hash, hostname, and environment in
the filename (e.g., `20231119T123456Z_abc1234_sugarkube0_just-up-dev.log`). The
helper prints the saved path at the end—even if you abort with <kbd>Ctrl</kbd>+<kbd>C</kbd>.

For clusters with multiple nodes on the same network, you can tune the hostname
allowlist to focus on specific machines:

```bash
MDNS_ALLOWED_HOSTS="sugarkube0 sugarkube1 token-place" just save-logs env=dev
```

**What you should see:** Only mDNS traffic from the specified hostnames appears in
the sanitized logs, keeping unrelated LAN devices out of the committed artifacts.

After capturing logs, review them for completeness and commit them to your
repository for future reference:

```bash
git add logs/up/
git commit -m "docs: add sanitized bring-up logs for dev cluster"
```

> **💡 Troubleshooting:** Need help interpreting your logs? The [Raspberry Pi Cluster Troubleshooting Guide](raspi_cluster_troubleshooting.md) explains how to read up logs and sanitized mDNS output, with examples of common failure scenarios and their solutions.

## Step 3: Deploy token.place

Now that your cluster is healthy, documented, and equipped with Helm, you're ready to deploy real
applications. [token.place](https://github.com/futuroptimist/token.place) is a sample workload
designed for Kubernetes clusters like yours.

### Clone the token.place repository

The token.place application is distributed as a Git repository with Helm charts.
If cloud-init didn't already clone it during Pi setup, do so now:

```bash
cd /opt/projects
git clone https://github.com/futuroptimist/token.place.git
```

**What you should see:** Git clones the repository and creates `/opt/projects/token.place/`
containing the application code and Helm charts.

### Prepare the Helm chart

Navigate to the charts directory and update dependencies:

```bash
cd /opt/projects/token.place/charts
helm dependency update token-place
```

**What you should see:** Helm downloads any chart dependencies defined in
`Chart.yaml` and stores them in the `charts/` subdirectory. If there are no
dependencies, you'll see `Saving 0 charts` which is normal.

### Deploy token.place to your cluster

Install the chart using Helm, creating a dedicated namespace and tagging the image
with the current Git commit:

```bash
helm upgrade --install token-place ./token-place \
  --namespace token-place --create-namespace \
  --set image.tag=$(git -C /opt/projects/token.place rev-parse --short HEAD)
```

**What you should see:** Helm creates the `token-place` namespace if it doesn't
exist, then installs or upgrades the release. Output shows the release name,
namespace, status (`deployed`), and revision number. The `image.tag` override
ensures you're running a specific version tied to the Git commit.

### Verify the token.place deployment

Check that all pods are running:

```bash
kubectl get pods -n token-place
```

**What you should see:** All token.place pods in `Running` state with `READY`
showing `1/1` or `2/2` depending on the number of containers per pod. If pods are
`Pending`, check events with `kubectl describe pod <pod-name> -n token-place`.

## Step 4: Deploy dspace

With token.place running, you can deploy additional workloads like
[democratized.space (dspace)](https://github.com/democratizedspace/dspace), a
companion application for your cluster.

> **Note:** There are two ways to deploy dspace:
> - **Manual Helm install** (documented below) by cloning the dspace repo and running
>   `helm upgrade --install ...` directly.
> - **Sugarkube + OCI Helm chart path** using `helm-oci-install` and the dspace v3 guide in the
>   dspace repo (recommended once Helm and GHCR login are working).
>
> For the sugarkube-centric path, see:
> https://github.com/democratizedspace/dspace/blob/v3/docs/k3s-sugarkube-dev.md

### Why deploy dspace?

dspace provides complementary functionality to token.place and demonstrates how to
run multiple applications on the same cluster. The deployment process is similar,
reinforcing the patterns you learned in Step 3.

### Clone the dspace repository

If it's not already present, clone the dspace repository:

```bash
cd /opt/projects
git clone https://github.com/democratizedspace/dspace.git
```

**What you should see:** Git clones the repository and creates `/opt/projects/dspace/`
with the application code and Helm charts.

### Prepare the Helm chart

Navigate to the dspace charts directory and update dependencies:

```bash
cd /opt/projects/dspace/charts
helm dependency update ./dspace
```

**What you should see:** Helm checks for chart dependencies. If no external
dependencies are defined, you'll see output indicating `Saving 0 charts`, which
is normal. This step ensures consistency with the pattern from Step 3 and
future-proofs the deployment if dependencies are added later.

### Deploy dspace to your cluster

Install the chart:

```bash
helm upgrade --install dspace ./dspace \
  --namespace dspace --create-namespace
```

**What you should see:** Helm creates the `dspace` namespace and deploys the
application. Output confirms the release status as `deployed`.

### Verify the dspace deployment

Check pod status:

```bash
kubectl get pods -n dspace
```

**What you should see:** All dspace pods in `Running` state with healthy readiness
checks.

If dspace includes an Ingress resource for external access, check it:

```bash
kubectl get ing -n dspace
```

**What you should see:** Ingress resources with assigned hosts and backend services.
If you configured a load balancer or Ingress controller, you'll see the external
address where dspace is accessible.

### Fast manual redeploy (emergency push for Helm workloads)

Once dspace (or any Helm release) is running, you can perform a fast, manual redeploy
whenever you push a new image tag. This path assumes the cluster is healthy, Traefik is
serving ingress, and the dspace OCI chart is already published to GHCR. The goal is to
roll pods quickly without extra ceremony—Kubernetes handles the rolling update using the
deployment's defaults.

**Quick redeploy for dspace v3 (OCI chart):**

```bash
# From the sugarkube repo root on a cluster node:
just helm-oci-upgrade \
  release=dspace namespace=dspace \
  chart=oci://ghcr.io/democratizedspace/charts/dspace \
  values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml \
  version_file=docs/apps/dspace.version \
  default_tag=v3-latest
```

The dspace chart also exposes a `DSPACE_ENV` environment variable (set via the top-level
`environment` value in the dspace values file). In this repo, `docs/examples/dspace.values.dev.yaml`
sets `environment: dev` and `docs/examples/dspace.values.staging.yaml` sets `environment: staging`,
which show up in `/healthz` and the homepage build badge.

If you prefer a one-liner that bakes in those arguments for dspace v3, use the helper
recipe:

```bash
just dspace-oci-redeploy
```

Under the hood, both commands call the shared `_helm-oci-deploy` helper via
`helm-oci-upgrade`, performing `helm upgrade --reuse-values` against the running release
and then forcing a `kubectl rollout restart deploy/dspace` to ensure pods recycle even
when `v3-latest` is republished with the same tag. The helper waits for the rollout to
finish and exits non-zero if Kubernetes reports a failure.

When you pass an image tag (including the default `v3-latest`), the helper sets
`image.pullPolicy=Always` so the nodes re-check GHCR for the latest build of that tag on
each redeploy. For production, prefer immutable tags (for example, `v3-<sha>`) if you want
to pin a specific image.

**Emergency redeploy checklist:**

1. Confirm the cluster and Traefik are healthy:

    ```bash
    just cluster-status
    ```

2. Ensure your new image is pushed and `v3-latest` (or the tag you pass via `tag=`)
   points at the desired build (see the dspace repo docs for image build/publish steps).
3. Run the redeploy command (`just helm-oci-upgrade ...` or `just dspace-oci-redeploy`).
4. Verify pods and logs:

    ```bash
    kubectl get pods -n dspace -o wide
    kubectl logs -n dspace -l app.kubernetes.io/name=dspace --tail=100
    ```

> This path is intentionally fast and slightly risky. For more conservative rollouts,
> consider tweaking replica counts or update strategies before running the upgrade.

### Collect dspace logs (emergency debugging)

When dspace returns HTTP 500 responses—either directly or via Traefik—you can dump the
most relevant logs in one shot from the sugarkube repo root on a cluster node:

```bash
just dspace-debug-logs
```

The recipe accepts an optional namespace override if your deployment differs:

```bash
just dspace-debug-logs namespace=my-dspace-namespace
```

What the output includes:

- A pod listing for the dspace namespace.
- The last 200 log lines for every pod labeled `app.kubernetes.io/name=dspace`.
- The last 200 lines of Traefik logs in `kube-system`.

Hints while reviewing the dump:

- Look for dspace JSON log entries with `"level":"error"` to pinpoint server failures.
- Scan the Traefik section for 5xx responses on hosts like `staging.democratized.space` to
  catch ingress-level issues.

## Step 5: Hook the cluster into Flux for GitOps

With your applications deployed manually, the final step is to automate future
deployments using GitOps. Flux watches your Git repository and automatically applies
changes to your cluster.

### Why use GitOps?

GitOps treats Git as the single source of truth for your infrastructure. When you
commit a change to your repository, Flux detects it and applies the update
automatically. This eliminates manual `kubectl apply` commands and provides an
audit trail of all changes.

### Bootstrap Flux on your cluster

Sugarkube includes a helper script to bootstrap Flux with the manifests in the
`flux/` directory:

```bash
just flux-bootstrap env=dev
```

**What you should see:** The script installs Flux controllers into the `flux-system`
namespace and configures them to watch your repository. Output shows the Flux
components being created (like `source-controller`, `kustomize-controller`,
`helm-controller`, and `notification-controller`).

Verify Flux is running:

```bash
kubectl get pods -n flux-system
```

**What you should see:** All Flux controller pods in `Running` state.

### Wire your applications into Flux

To have Flux manage your token.place and dspace deployments, commit Helm release
manifests under `clusters/<env>/`. For example, create
`clusters/dev/token-place-release.yaml`:

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2beta1
kind: HelmRelease
metadata:
  name: token-place
  namespace: token-place
spec:
  chart:
    spec:
      chart: ./token-place
      sourceRef:
        kind: GitRepository
        name: token-place
  interval: 10m
```

> **Note:** This is a simplified example showing the HelmRelease structure. In
> practice, you'll also need to create a GitRepository resource that points to
> your token.place repository, or use a HelmRepository if the chart is published
> to a Helm repository. See the [Flux documentation](https://fluxcd.io/flux/components/source/)
> for complete GitRepository and HelmRepository configuration examples.

Commit and push this file. Flux will detect the change and deploy the release
automatically.

**What you should see:** After committing, Flux reconciles the change within a few
minutes. Check the HelmRelease status:

```bash
kubectl get helmrelease -A
```

You should see `token-place` with a `Ready` condition indicating successful deployment.

## Additional operational recipes

As you continue operating your cluster, these recipes will be helpful:

- **Test token.place samples:** Run `just token-place-samples` to replay bundled
  health checks before exposing the workloads to external traffic.

- **Reconcile platform changes:** Use `just platform-apply env=dev` to trigger an
  immediate Flux reconciliation of the platform Kustomization.

- **Seal secrets:** Run `just seal-secrets env=dev` to reseal SOPS secrets for your
  environment using the cluster's public key.

- **Recover from misconfiguration:** If a node accidentally joins the wrong cluster,
  use `just wipe` to clean it up, then rerun `just ha3 env=dev` to rejoin correctly.

- **Emergency dspace redeploy:** Run `just dspace-oci-redeploy` to pull the latest
  dspace v3 chart from GHCR and force a rollout restart so pods refresh to the newest
  `v3-latest` image digest without retyping chart arguments.

### Document outages and incidents

For outages or retrospectives, use the structured templates under `outages/` and
cross-link your sanitized logs. This maintains a historical record and helps identify
patterns over time.

## Exercises

Apply your operational knowledge with these hands-on tasks:

1. **Scale a deployment:** Use `kubectl scale deployment <name> --replicas=3 -n token-place` to scale the token.place deployment to three replicas. Verify the new pods are running with `kubectl get pods -n token-place` and observe load distribution across nodes.

2. **Pod log inspection:** Pick any running pod from `kubectl get pods -A` and examine its logs with `kubectl logs <pod-name> -n <namespace>`. If the pod has multiple containers, use `-c <container-name>` to view a specific container's output.

3. **Add an annotation:** Choose a deployment in the `token-place` or `dspace` namespace and add a custom annotation with `kubectl annotate deployment <name> -n <namespace> example.com/owner=yourname`. Verify the annotation appears in `kubectl describe deployment <name> -n <namespace>`.

4. **Helm value override:** Temporarily change a Helm value for token.place by running `helm upgrade token-place ./token-place --namespace token-place --set replicaCount=2` from the `/opt/projects/token.place/charts` directory (or the charts directory at the root of your token.place project). Check the effect with `kubectl get deployment -n token-place` to see the updated replica count.

5. **Cluster health check:** Use `kubectl get componentstatuses` (deprecated but educational; may not work on k3s v1.26+ and newer) or `kubectl get --raw /healthz` to query the cluster's overall health status. Then run `kubectl top nodes` to see CPU and memory usage across the control plane.

## Next steps

Your cluster is now fully operational with applications running and GitOps
configured. Explore additional guides:

- Adjust Helm values files to add TLS hosts, Ingress classes, or secrets
- Set up monitoring and alerting for your workloads
- Configure backups using k3s's built-in etcd snapshot feature
- Review [docs/runbook.md](./runbook.md) for deeper SRE playbooks
