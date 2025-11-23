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

## Install and verify Traefik ingress

**Prerequisite:** Ensure Helm is installed and `just helm-status` succeeds (see the "Install Helm"
section above). For the underlying manual commands, see
`docs/raspi_cluster_operations_manual.md#1-install-helm-manually`.

Sugarkube clusters expect a Kubernetes ingress controller to route HTTP(S) traffic into your
services. The docs and examples in this repo assume [Traefik](https://traefik.io/) as the default
ingress controller. Other controllers can work, but this guide only documents the Traefik path.

Check whether Traefik already exists in the `kube-system` namespace:

```bash
sudo kubectl -n kube-system get svc -l app.kubernetes.io/name=traefik
```

- If the command returns a `traefik` service (ClusterIP or LoadBalancer), continue to the next
  section.
- If it prints `No resources found in kube-system namespace.`, install Traefik before deploying
  apps.

For the shortest path, install Traefik via the new helper recipe:

```bash
just traefik-install
```

This installs Traefik into `kube-system`, waits for readiness, and prints the discovered
service. Re-run the status recipe any time to check the ingress controller:

```bash
just traefik-status
```

Traefik is not installed automatically by the base cluster bootstrap. To add it using the
official Helm chart:

```bash
helm repo add traefik https://traefik.github.io/charts
helm repo update
helm upgrade --install traefik traefik/traefik \
  --namespace kube-system \
  --create-namespace \
  --set service.type=ClusterIP \
  --wait
```

This installs a minimal Traefik release into `kube-system` with a ClusterIP service. Adjust the
Helm values or refer to the [official Traefik docs](https://doc.traefik.io/traefik/) for
advanced configuration such as TLS, load balancers, or custom entrypoints.

After installation, re-run:

```bash
kubectl -n kube-system get svc -l app.kubernetes.io/name=traefik
```

and confirm the `traefik` service exists before continuing. The dspace v3 k3s-sugarkube-dev
guide assumes Traefik is installed and reachable via this flow.

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
