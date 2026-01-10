---
personas:
  - hardware
  - software
---

# Raspberry Pi Cluster Operations (Manual)

**📚 Manual companion to Part 3** in the
[Raspberry Pi cluster series](index.md#raspberry-pi-cluster-series)
- **Quick path:** [raspi_cluster_operations.md](raspi_cluster_operations.md)
- **Previous:** [raspi_cluster_setup.md](raspi_cluster_setup.md)
- **Foundation:** [raspi_cluster_setup_manual.md](raspi_cluster_setup_manual.md)

Use this manual when you need the long-form commands that back the day-two helpers
in `raspi_cluster_operations.md`. It pairs each automated recipe with an equivalent
shell sequence so you can reason about every change or adapt it to nonstandard
clusters.

## What the quick start automates

- **Ingress verification:** k3s installs Traefik by default. `just traefik-status`
  lists the Traefik service and pods, and `just traefik-crd-doctor` checks Gateway
  API CRD ownership. Manually, run `sudo kubectl -n kube-system get svc,po -l app.kubernetes.io/name=traefik`.
- **Cloudflare Tunnel:** Run `just cf-tunnel-install env=dev` with your
  Cloudflare tunnel token to create the namespace, store the secret, and install
  the Helm chart. The manual path mirrors those steps in §3.
- **Sanitized bring-up logs:** `just save-logs env=dev` wraps `just up` with the
  log filter. Manually, export `SAVE_DEBUG_LOGS=1`, set `SUGARKUBE_LOG_FILTER`
  to `scripts/filter_debug_log.py`, and run `just up dev`.
- **Flux bootstrap:** `just flux-bootstrap env=dev` patches and applies the Flux
  manifests. The manual path is to edit `flux/gotk-sync.yaml` with your repo and
  apply both Flux YAML files directly.

## Prerequisites

- `kubectl` and `helm` available on the node or workstation you are using
- A kubeconfig that can reach the cluster API. On a control-plane node, copy the
  built-in config and retarget it to localhost:

  ```bash
  sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
  sudo chown $(id -u):$(id -g) ~/.kube/config
  sed -i "s/127.0.0.1/localhost/" ~/.kube/config
  ```

- Network reachability from your workstation to the cluster if you are managing
  it remotely.

## 1. Install Helm manually

If Helm is missing, install it with the official script used by the `just` recipe:

```bash
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

Verify the binary is available and on your path:

```bash
helm version
which helm
```

**What you should see:** A Helm 3 version string (e.g., `version.BuildInfo{Version:"v3.13.0", ...}`)
and a path such as `/usr/local/bin/helm`.

If you prefer to use the high-level Just recipes instead of running these commands manually, see the
“Install Helm” section in `docs/raspi_cluster_operations.md` and run `just helm-install` followed by
`just helm-status`.

## 2. Verify and diagnose Traefik ingress manually

The manual commands here are the low-level equivalent of the `just traefik-status` and
`just traefik-crd-doctor` sequence described in the golden path.

Note that `just traefik-crd-doctor` remains the primary way to validate CRDs in both flows.

Most users should stick with the verification flow in
[raspi_cluster_operations.md](raspi_cluster_operations.md). Traefik is installed by k3s via addon
HelmChart objects, so only reach for `just traefik-install` if you intentionally want to manage
Traefik yourself. Use the manual path here when debugging or applying custom Traefik settings. The
automated CRD doctor performs a Gateway API CRD ownership preflight and will stop with a
descriptive error if existing CRDs are missing the Helm metadata that Traefik expects; the commands
below are the underlying delete/patch options you can run when that happens. Run
`just traefik-crd-doctor` in dry-run mode before or after these steps: "all missing" CRDs or "all
healthy" CRDs are good outcomes, and only conflicting ownership states need remediation.

To mirror the automated kubeconfig behavior manually before running kubectl:

```bash
export KUBECONFIG="$HOME/.kube/config"
kubectl get nodes
```

This keeps all commands pointed at the user-owned kubeconfig instead of `/etc/rancher/k3s/k3s.yaml`.

Ensure Helm is installed (see "Install Helm manually" above) before proceeding.

Check whether Traefik is already present:

```bash
sudo kubectl -n kube-system get svc -l app.kubernetes.io/name=traefik
```

- If the command returns a `traefik` service (ClusterIP or LoadBalancer), keep
  going.
- If it prints `No resources found in kube-system namespace.`, inspect the k3s
  addon HelmChart objects and Helm install jobs:

  ```bash
  sudo kubectl -n kube-system get helmchart,helmchartconfig | grep -i traefik || true
  sudo kubectl -n kube-system get pods -o wide | egrep 'traefik|helm-install-traefik' || true
  ```

Run the CRD doctor to validate ownership:

```bash
just traefik-crd-doctor
```

Re-run the service check and note the ClusterIP or LoadBalancer address:

```bash
sudo kubectl -n kube-system get svc,po -l app.kubernetes.io/name=traefik
```

### Advanced override: install Traefik with Helm manually

If you intend to manage Traefik yourself (non-default for sugarkube), install the official chart:

```bash
helm repo add traefik https://traefik.github.io/charts
helm repo update
helm upgrade --install traefik traefik/traefik \
  --namespace kube-system \
  --create-namespace \
  --set service.type=ClusterIP \
  --set experimental.kubernetesGateway.enabled=true \
  --set providers.kubernetesGateway.enabled=true \
  --set gateway.enabled=true \
  --set gatewayClass.enabled=true \
  --wait
```

These values enable Traefik's Kubernetes Gateway controller and associated CRDs so that the main
`traefik` release owns them. Existing clusters using a legacy `traefik-crd` release (from k3s) are
still accepted by the CRD doctor; new installs will use the main `traefik` release as the CRD owner.

## 3. Manual cluster, Helm, and Traefik status checks

Use these raw commands to mirror what `just cluster-status` reports.

- **Cluster nodes:** Shows all nodes, their readiness, roles, versions, and IPs.

  ```bash
  sudo kubectl get nodes -o wide
  ```

- **Helm CLI:** Confirms Helm is installed and discoverable on PATH.

  ```bash
  helm version --short
  which helm
  ```

- **Traefik and ingress:** Lists Traefik pods/services in `kube-system` and any ingress classes.

  ```bash
  sudo kubectl -n kube-system get pods -l app.kubernetes.io/name=traefik
  sudo kubectl -n kube-system get svc -l app.kubernetes.io/name=traefik
  sudo kubectl get ingressclass
  ```

The `just cluster-status` command in `raspi_cluster_operations.md` is a wrapper around these
manual checks.

## 4. Expose your first app (manual ingress path)

This mirrors the quick-start flow that relies on Traefik and Cloudflare Tunnel,
but spells out the underlying commands.

1. Create the Cloudflare namespace and secret on a node that can reach the
   cluster API:

   ```bash
   sudo kubectl get namespace cloudflare >/dev/null 2>&1 || sudo kubectl create namespace cloudflare
   sudo kubectl -n cloudflare create secret generic tunnel-token \
     --from-literal=token="<cloudflare-tunnel-token>" \
     --dry-run=client -o yaml | sudo kubectl apply -f -
   ```

2. Install the Cloudflare Tunnel connector in remote-managed token mode (same
   shape as `just cf-tunnel-install`):

   ```bash
   export CF_TUNNEL_NAME="${CF_TUNNEL_NAME:-sugarkube-dev}"   # Optional override to match the dashboard

   just cf-tunnel-install env=dev token="$CF_TUNNEL_TOKEN"
   ```

   This patches the Helm deployment to run `cloudflared tunnel --no-autoupdate
   --metrics 0.0.0.0:2000 run` with `TUNNEL_TOKEN` from the `tunnel-token`
   Secret, and removes all origin-certificate / `credentials.json` config so
   the pod behaves strictly as a remote-managed tunnel.

3. Create a Cloudflare route from your chosen FQDN to
   `http://traefik.kube-system.svc.cluster.local:80` in the dashboard. Use the
   Traefik service output from the previous step if you need to confirm the
   service name.

4. Deploy your application (for example, follow [apps/dspace.md](apps/dspace.md)
   to install dspace v3 with a Traefik Ingress host) and verify ingress and
   pod health:

   ```bash
   sudo kubectl -n <app-namespace> get ingress,pods,svc
   ```

## 5. Verify the 3-node control plane by hand

Check node readiness without the `just status` wrapper:

```bash
sudo kubectl get nodes -o wide
watch -n5 sudo kubectl get nodes
```

Review system pods and describe any nodes that look unhealthy:

```bash
sudo kubectl get pods -A
sudo kubectl describe node <name>
```

If you prefer workstation access, copy the kubeconfig from a control-plane node
and rename the context to avoid collisions:

```bash
scp pi@<control-plane-host>:/etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo kubectl config rename-context default sugar-dev
```

## 6. Capture sanitized bring-up logs manually

The `just save-logs` recipe wraps a log filter around `just up`. To do it
yourself:

```bash
export SAVE_DEBUG_LOGS=1
export SUGARKUBE_LOG_FILTER=$(pwd)/scripts/filter_debug_log.py
export SAVE_DEBUG_LOGS_DIR=$(pwd)/logs/up
just up dev
unset SAVE_DEBUG_LOGS
```

The filtered log prints its destination when the run finishes (or when you
press <kbd>Ctrl</kbd>+<kbd>C</kbd>). Commit the sanitized file under `logs/up/`
for future debugging.

## 7. Deploy token.place manually

With Helm installed (see "Install Helm manually" above), clone the repository and update dependencies:

```bash
cd /opt/projects
git clone https://github.com/futuroptimist/token.place.git
cd token.place/charts
helm dependency update token-place
```

Deploy the chart with a commit-tagged image:

```bash
helm upgrade --install token-place ./token-place \
  --namespace token-place --create-namespace \
  --set image.tag=$(git -C /opt/projects/token.place rev-parse --short HEAD)
sudo kubectl get pods -n token-place
```

## 8. Deploy dspace

Clone and deploy the dspace chart:

```bash
cd /opt/projects
git clone https://github.com/democratizedspace/dspace.git
cd dspace/charts
helm dependency update ./dspace

helm upgrade --install dspace ./dspace \
  --namespace dspace --create-namespace
sudo kubectl get pods -n dspace
sudo kubectl get ing -n dspace
```

Use the Ingress host from the final command to reach dspace through Traefik and
your Cloudflare tunnel.

## 9. Bootstrap Flux without the helper

Update `flux/gotk-sync.yaml` so the `GitRepository` URL and
`spec.path` point at your repository and environment. Then apply the bundled
manifests directly:

```bash
sudo kubectl create namespace flux-system --dry-run=client -o yaml | sudo kubectl apply -f -
sudo kubectl apply -f flux/gotk-components.yaml
sudo kubectl apply -f flux/gotk-sync.yaml
sudo kubectl -n flux-system get pods
```

Once the controllers are running, Flux will reconcile the sources and
Kustomizations you referenced in `gotk-sync.yaml`.

## 10. Additional manual operations

- **Scale workloads:** `sudo kubectl scale deployment <name> --replicas=3 -n <ns>`.
- **Inspect logs:** `sudo kubectl logs <pod> -n <ns>` (use `-c` for multi-container
  pods).
- **Override Helm values temporarily:** run `helm upgrade <release> <chart> \
  --namespace <ns> --reuse-values --set key=value` and confirm the change with
  `sudo kubectl get deployment -n <ns>`.
- **Heal a bad join:** `just wipe` remains the fastest way to reset a node
  before re-running `just ha3 env=dev`, but you can also remove k3s manually by
  following the official uninstall script from `/usr/local/bin/k3s-uninstall.sh`.

Your cluster now mirrors the quick-start state with full control over every
command used to get there.
