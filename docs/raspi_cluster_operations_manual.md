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

- **Ingress install:** `just traefik-install` adds the Traefik Helm repo,
  installs the chart into `kube-system`, waits for readiness, and prints the
  service. The manual equivalent runs the `helm repo add` and
  `helm upgrade --install` commands shown below.
- **Ingress checks:** `just traefik-status` lists the Traefik service and pods.
  Manually, run `kubectl -n kube-system get svc,po -l app.kubernetes.io/name=traefik`.
- **Cloudflare Tunnel:** Run `just cf-tunnel-install env=dev` with your
  Cloudflare tunnel token to create the namespace, store the secret, and install
  the Helm chart. The manual path mirrors those steps in §2.
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

## 1. Install and verify Traefik ingress manually

Check whether Traefik is already present:

```bash
kubectl -n kube-system get svc -l app.kubernetes.io/name=traefik
```

- If the command returns a `traefik` service (ClusterIP or LoadBalancer), keep
  going.
- If it prints `No resources found in kube-system namespace.`, install Traefik
  before deploying HTTP applications.

Install Traefik with the official Helm chart:

```bash
helm repo add traefik https://traefik.github.io/charts
helm repo update
helm upgrade --install traefik traefik/traefik \
  --namespace kube-system \
  --create-namespace \
  --wait
```

Re-run the service check and note the ClusterIP or LoadBalancer address:

```bash
kubectl -n kube-system get svc,po -l app.kubernetes.io/name=traefik
```

## 2. Expose your first app (manual ingress path)

This mirrors the quick-start flow that relies on Traefik and Cloudflare Tunnel,
but spells out the underlying commands.

1. Create the Cloudflare namespace and secret on a node that can reach the
   cluster API:

   ```bash
   kubectl get namespace cloudflare >/dev/null 2>&1 || kubectl create namespace cloudflare
   kubectl -n cloudflare create secret generic tunnel-token \
     --from-literal=token="<cloudflare-tunnel-token>" \
     --dry-run=client -o yaml | kubectl apply -f -
   ```

2. Install the Cloudflare Tunnel Helm chart:

   ```bash
   helm repo add cloudflare https://cloudflare.github.io/helm-charts --force-update
   helm repo update cloudflare

   helm upgrade --install cloudflare-tunnel cloudflare/cloudflare-tunnel \
     --namespace cloudflare \
     --create-namespace \
     --wait \
     --set cloudflare.tunnelName="${CF_TUNNEL_NAME:-sugarkube-dev}" \
     --set cloudflare.tunnelId="${CF_TUNNEL_ID:-}" \
     --set cloudflare.secretName=tunnel-token \
     --set cloudflare.ingress="{}"
   ```

3. Create a Cloudflare route from your chosen FQDN to
   `http://traefik.kube-system.svc.cluster.local:80` in the dashboard. Use the
   Traefik service output from the previous step if you need to confirm the
   service name.

4. Deploy your application (for example, follow [apps/dspace.md](apps/dspace.md)
   to install dspace v3 with a Traefik Ingress host) and verify ingress and
   pod health:

   ```bash
   kubectl -n <app-namespace> get ingress,pods,svc
   ```

## 3. Verify the 3-node control plane by hand

Check node readiness without the `just status` wrapper:

```bash
kubectl get nodes -o wide
watch -n5 kubectl get nodes
```

Review system pods and describe any nodes that look unhealthy:

```bash
kubectl get pods -A
kubectl describe node <name>
```

If you prefer workstation access, copy the kubeconfig from a control-plane node
and rename the context to avoid collisions:

```bash
scp pi@<control-plane-host>:/etc/rancher/k3s/k3s.yaml ~/.kube/config
kubectl config rename-context default sugar-dev
```

## 4. Capture sanitized bring-up logs manually

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

## 5. Install Helm and deploy token.place

If Helm is missing, install it first:

```bash
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
helm version
```

Clone the repository and update dependencies:

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
kubectl get pods -n token-place
```

## 6. Deploy dspace

Clone and deploy the dspace chart:

```bash
cd /opt/projects
git clone https://github.com/democratizedspace/dspace.git
cd dspace/charts
helm dependency update ./dspace

helm upgrade --install dspace ./dspace \
  --namespace dspace --create-namespace
kubectl get pods -n dspace
kubectl get ing -n dspace
```

Use the Ingress host from the final command to reach dspace through Traefik and
your Cloudflare tunnel.

## 7. Bootstrap Flux without the helper

Update `flux/gotk-sync.yaml` so the `GitRepository` URL and
`spec.path` point at your repository and environment. Then apply the bundled
manifests directly:

```bash
kubectl create namespace flux-system --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f flux/gotk-components.yaml
kubectl apply -f flux/gotk-sync.yaml
kubectl -n flux-system get pods
```

Once the controllers are running, Flux will reconcile the sources and
Kustomizations you referenced in `gotk-sync.yaml`.

## 8. Additional manual operations

- **Scale workloads:** `kubectl scale deployment <name> --replicas=3 -n <ns>`.
- **Inspect logs:** `kubectl logs <pod> -n <ns>` (use `-c` for multi-container
  pods).
- **Override Helm values temporarily:** run `helm upgrade <release> <chart> \
  --namespace <ns> --reuse-values --set key=value` and confirm the change with
  `kubectl get deployment -n <ns>`.
- **Heal a bad join:** `just wipe` remains the fastest way to reset a node
  before re-running `just ha3 env=dev`, but you can also remove k3s manually by
  following the official uninstall script from `/usr/local/bin/k3s-uninstall.sh`.

Your cluster now mirrors the quick-start state with full control over every
command used to get there.
