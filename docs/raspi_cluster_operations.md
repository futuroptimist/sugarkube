---
personas:
  - hardware
  - software
---

# Raspberry Pi Cluster Operations & Helm

This companion to [raspi_cluster_setup.md](./raspi_cluster_setup.md) starts where the
happy-path bring-up ends. It shows how to verify cluster status, capture sanitized
logs, harden networking, and install Helm-based workloads such as
[token.place](https://github.com/futuroptimist/token.place) and
[democratized.space (dspace)](https://github.com/democratizedspace/dspace).

## 1. Check cluster health and capture logs

1. Confirm k3s is reachable:
   ```bash
   just status          # wraps `kubectl get nodes -o wide`
   kubectl get pods -A  # optionally add `-w` to watch state transitions
   ```
2. Need the control-plane join string again? `just cat-node-token` prints
   `/var/lib/rancher/k3s/server/node-token` with the right privileges and exits
   gracefully on agents that do not own the token.
3. Capture sanitized transcripts whenever you rerun `just up`:
   ```bash
   just save-logs env=dev
   ```
   Behind the scenes this exports `SAVE_DEBUG_LOGS=1`, runs the normal `just up`
   flow, and writes timestamped files like
   `logs/up/20250221T183000Z_ab12cd3_sugarkube0_just-up-dev.log`. Logs stream to
   the console in real time while the helper strips secrets and public IPs before
   the data lands on disk.
4. Manually control log capture when you need to inspect a single command:
   ```bash
   export SAVE_DEBUG_LOGS=1
   just up dev
   unset SAVE_DEBUG_LOGS
   ```
5. Filter the mDNS hosts that appear in debug captures to avoid leaking details
   about unrelated devices on your LAN:
   ```bash
   export MDNS_ALLOWED_HOSTS="sugarkube0 sugarkube1 sugarkube2"
   MDNS_ALLOWED_HOSTS="sugarkube0 sugarkube1 myprinter" ./logs/debug-mdns.sh
   ```
   Hostnames should be supplied without the `.local` suffix. The helper appends
   it automatically and restricts the scrubbed logs to your allowlist.

## 2. Hardening and quality-of-life improvements

- **High-availability defaults**: `just 3ha env=dev` wraps the dual-run `just up`
  flow with `SUGARKUBE_SERVERS=3`, ensuring each server participates in the
  embedded-etcd quorum without typing extra exports after every reboot.
- **Registration address**: Export `SUGARKUBE_API_REGADDR` (or add it to your
  shell profile) so agents always join through a virtual IP or load balancer.
- **mDNS firewalling**: Run `just mdns-harden` to reapply the Avahi drop-in that
  pins Sugarkube's DNS-SD service type and timeout settings.
- **WLAN determinism**: When bootstrapping over Ethernet, `just wlan-down`
  disables Wi-Fi until Sugarkube reenables it. This prevents DHCP flapping and
  makes troubleshooting easier.
- **Post-bootstrap hygiene**: `just wipe` tears down a misconfigured node by
  removing k3s, the Avahi service file, and every documented environment
  variable, then waits for the cluster advertisement to disappear before
  returning.

## 3. Install Helm and kubectl access locally

1. Copy the kubeconfig to your workstation:
   ```bash
   just kubeconfig env=dev
   scp pi@sugarkube0.local:.kube/config ~/.kube/config.sugarkube-dev
   ```
2. Install Helm 3 on your workstation or directly on a Pi:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
   helm version
   ```
3. Enable tab completion and cache chart repositories:
   ```bash
   helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
   helm repo update
   ```
4. Optional: install `metrics-server` or `kube-prometheus-stack` to unlock
   resource telemetry before deploying applications.

## 4. Deploy token.place and dspace with Helm

1. Clone the application repositories onto your workstation or a builder host:
   ```bash
   git clone https://github.com/futuroptimist/token.place.git
   git clone https://github.com/democratizedspace/dspace.git
   ```
2. Scaffold a chart for each service (use one namespace per environment):
   ```bash
   helm create charts/token-place
   helm create charts/dspace
   ```
3. Replace the default container image settings in `values.yaml` with the public
   registries the projects publish:
   ```yaml
   image:
     repository: ghcr.io/futuroptimist/token.place
     tag: latest
   env:
     TOKEN_PLACE_ENV: dev
   service:
     type: ClusterIP
     port: 5000
   ```
4. Reference the dspace image and port (5050 by default) in its chart and add an
   Ingress stanza when you want Cloudflare Tunnel or an internal load balancer to
   expose the service:
   ```yaml
   image:
     repository: ghcr.io/democratizedspace/dspace
     tag: latest
   service:
     port: 5050
   ingress:
     enabled: true
     className: nginx
     hosts:
       - host: dspace.dev.sugar.local
         paths:
           - path: /
             pathType: Prefix
   ```
5. Deploy the charts:
   ```bash
   helm upgrade --install token-place charts/token-place -n dev --create-namespace -f charts/token-place/values.yaml
   helm upgrade --install dspace charts/dspace -n dev -f charts/dspace/values.yaml
   ```
6. Validate the services:
   ```bash
   kubectl get pods -n dev
   kubectl get svc -n dev token-place dspace
   python -m sugarkube_toolkit token-place samples --dry-run
   ```
   The final command reuses the bundled `samples/token_place/` payloads to prove
   the API responds before you invite real traffic.

## 5. Routine maintenance checklist

- Watch cluster utilization with `kubectl top nodes` (after installing
  `metrics-server`).
- Rotate `just save-logs env=dev` captures into `logs/up/` whenever a node is
  touched so outages have forensic context.
- Keep Avahi and Helm charts current by running `sudo apt update && sudo apt
  upgrade` plus `helm repo update` on a regular cadence.
- Graduate to [docs/runbook.md](./runbook.md) when you need incident response
  drills or GitOps procedures.
