---
personas:
  - hardware
  - software
---

# Raspberry Pi Cluster Operations & Helm Workloads

`raspi_cluster_setup.md` gets every Raspberry Pi onto the same HA k3s control plane.
This follow-up guide covers the day-two routine: checking cluster health, capturing
logs, preparing Helm, and rolling out real workloads like
[token.place](https://github.com/futuroptimist/token.place) and
[democratized.space (dspace)](https://github.com/democratizedspace/dspace).

> **Prerequisite**
> Complete the 3-server quick-start in [raspi_cluster_setup.md](./raspi_cluster_setup.md)
> so every Pi already shares the same token and environment.

## Quick status checks

| Command | Purpose |
|---------|---------|
| `just status` | Shows `kubectl get nodes -o wide` using the embedded kubeconfig. |
| `just kubeconfig env=dev` | Copies `/etc/rancher/k3s/k3s.yaml` to `~/.kube/config` and renames the context to `sugar-dev`. |
| `kubectl get pods -A` | Confirm workloads finished scheduling. |
| `kubectl describe node <name>` | Inspect taints, kubelet config, and resource pressure. |

The `just status` recipe guards against running before k3s exists and prints a
helpful reminder if the control plane is missing. Follow it with
`watch -n5 kubectl get nodes` when waiting for the third HA node to report `Ready`.

## Shortcut recipes for the bring-up journey

Sugarkube now exposes smaller recipes that wrap the long environment exports used
throughout the quick-start:

| Recipe | What it does |
|--------|--------------|
| `just 3ha env=dev` | Sets `SUGARKUBE_SERVERS=3` and executes `just up dev`, enabling the HA control-plane flow without retyping the export. |
| `just save-logs env=dev` | Runs `just up <env>` with `SAVE_DEBUG_LOGS=1`, capturing sanitized logs under `logs/up/`. |
| `just cat-node-token` | Prints `/var/lib/rancher/k3s/server/node-token` via `sudo` so you can copy it into `SUGARKUBE_TOKEN_<ENV>` quickly. |

You can mix-and-match these helpers. Example timeline for an HA node:

```bash
just 3ha env=dev              # 1st run patches memory cgroups and reboots
just 3ha env=dev              # 2nd run bootstraps/join k3s automatically
just cat-node-token           # Copy token for future nodes or clusters
```

Need logs from a flaky run? Swap the second command with `just save-logs env=dev`
so the sanitizer records everything.

## Capturing sanitized bootstrap logs

The log helper moved out of the quick-start so this guide can cover it in more
detail. Enable capture temporarily before the second `just up` run:

```bash
just save-logs env=dev
# or, if you need more control:
SAVE_DEBUG_LOGS=1 just up dev
unset SAVE_DEBUG_LOGS  # stop logging in this shell
```

`SAVE_DEBUG_LOGS=1` streams console output through `scripts/filter_debug_log.py`
and writes a sanitized copy to `logs/up/` with a timestamp, commit hash, hostname,
and environment baked into the filename. The helper prints the saved path at the
end—even if you abort with <kbd>Ctrl</kbd>+<kbd>C</kbd>.

Tune the hostname allowlist for mDNS debug captures (useful when committing logs):

```bash
MDNS_ALLOWED_HOSTS="sugarkube0 sugarkube1 token-place" just save-logs env=dev
```

That keeps unrelated LAN devices out of the committed artifacts.

## Install Helm and prep app releases

Helm is already available on the Pi image, but if you built a minimal OS run the
upstream installer:

```bash
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
helm version
```

1. **Clone your projects** (when cloud-init didn't already do it):
   ```bash
   cd /opt/projects
   git clone https://github.com/futuroptimist/token.place.git
   git clone https://github.com/democratizedspace/dspace.git
   ```
2. **Explore each chart**. Both repositories include Helm charts under their
   respective `charts/` directories. Update dependencies before you install:
   ```bash
   cd /opt/projects/token.place/charts
   helm dependency update token-place
   ```
3. **Install or upgrade** the workloads:
   ```bash
   helm upgrade --install token-place ./token-place \
     --namespace token-place --create-namespace \
     --set image.tag=$(git -C /opt/projects/token.place rev-parse --short HEAD)

   helm upgrade --install dspace ./dspace \
     --namespace dspace --create-namespace
   ```
4. **Verify** the deployments:
   ```bash
   kubectl get pods -n token-place
   kubectl get ing -n dspace
   ```

Adjust the values files to add TLS hosts, Ingress classes, or secrets. Once the
cluster is steady, wire the charts into Flux by committing manifests under
`clusters/<env>/` so future releases land via GitOps.

## Keep iterating on the cluster

- `just flux-bootstrap env=dev` to install Flux with the manifests in `flux/`.
- `just token-place-samples` to replay the bundled health checks before exposing
  the workloads.
- `just wipe` whenever a node joins the wrong cluster—then rerun `just 3ha env=dev`.

For outages or retro write-ups, use the templates under `outages/` and cross-link
your sanitized logs.
