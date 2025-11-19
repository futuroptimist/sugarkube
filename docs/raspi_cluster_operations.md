---
personas:
  - hardware
  - software
---

# Raspberry Pi Cluster Operations & Workloads

This guide picks up immediately after [raspi_cluster_setup.md](./raspi_cluster_setup.md). The
`just up <env>` happy path is already proven on hardware (see `logs/up/` and the most recent
`outages/` entries). Now we focus on:

- Verifying the control plane is healthy
- Capturing artifacts for later debugging
- Installing Helm and shipping real workloads such as token.place and dspace
- Adding quality-of-life wrappers so running a three-node HA cluster requires fewer manual exports

## 1. Confirm the cluster is healthy

1. Watch the nodes settle:
   ```bash
   just status
   # or
   kubectl get nodes -o wide
   ```
   Expect all three servers to report `Ready` once their second `just up dev` run has finished.
2. Inspect pods cluster-wide:
   ```bash
   kubectl get pods -A -o wide
   ```
3. Surface the join token anytime without hunting for the path:
   ```bash
   just cat-node-token
   ```
   Copy the `K10…` string into a secure vault—you'll export it on every joining node.
4. Fetch a kubeconfig locally for workstation access:
   ```bash
   just kubeconfig env=dev
   ```
5. Troubleshoot networking if discovery stalls:
   ```bash
   just mdns-harden
   just mdns-selfcheck env=dev
   ```

## 2. Fast wrappers for common flows

Running `export SUGARKUBE_SERVERS=3 && SAVE_DEBUG_LOGS=1` over and over is easy to forget. The
following `just` recipes set those flags for you:

| Recipe | Replaces | When to use |
|--------|----------|-------------|
| `just ha3 env=dev` | `export SUGARKUBE_SERVERS=3 && just up dev` | Run twice per Pi to stand up an HA control plane without typing the export each time. |
| `just save-logs env=dev` | `SAVE_DEBUG_LOGS=1 just up dev` | Capture sanitized logs under `logs/up/` during a bootstrap or join attempt. |
| `just cat-node-token` | `sudo cat /var/lib/rancher/k3s/server/node-token` | Print the server token with one command and a friendly error if k3s is not installed yet. |

> `just` forbids recipe names that start with digits, so `ha3` is the closest spelling to the
> requested `3ha` shorthand.

These wrappers still honor every environment variable documented in the quick start—use them as
thin veneers that save keystrokes while keeping the intent explicit.

## 3. Capture and review logs or outages

1. Run `just save-logs env=dev` on any bootstrap or join attempt to tee sanitized output into
   `logs/up/<timestamp>_<commit>_<hostname>_just-up-<env>.log`.
2. Set `MDNS_ALLOWED_HOSTS` before a run if you need the mDNS debugger to redact non-cluster
   devices: `MDNS_ALLOWED_HOSTS="sugarkube0 sugarkube1" just save-logs env=dev`. Hostnames should be
   specified without the `.local` suffix; the sanitizer defaults to `sugarkube0 sugarkube1
   sugarkube2` when you omit the variable.
3. Summarize the last run:
   ```bash
   tail -n 40 logs/up/*just-up-dev.log
   ```
4. File outages under `outages/` when regressions reappear. Use the schema enforced by
   `outages/schema.json` so future investigators can correlate symptoms with log captures.

## 4. Install Helm on the cluster

Helm is optional for the base bootstrap but required for GitOps bundles and bespoke workloads:

```bash
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
helm version
```

Place the binary on every admin workstation that talks to the cluster. On Pis, `/usr/local/bin/helm`
works well; on macOS or Linux workstations, install via Homebrew, `scoop`, or the official script
above.

### Bootstrap shared repositories

1. Add the repositories you rely on:
   ```bash
   helm repo add bitnami https://charts.bitnami.com/bitnami
   helm repo update
   ```
2. Keep release definitions in Git where possible—`platform/` already uses GitOps-friendly overlays
   for Flux, so referencing charts there keeps history discoverable.

## 5. Deploy token.place and dspace with Helm

Use separate namespaces so each surface can evolve independently while sharing cluster services.
Below is a lightweight example that matches the images referenced in
[cluster-rollout-and-migrations.md](./cluster-rollout-and-migrations.md).

1. Create namespaces and secrets for each workload (replace placeholders with your values):
   ```bash
   kubectl create namespace token-place --dry-run=client -o yaml | kubectl apply -f -
   kubectl create namespace dspace --dry-run=client -o yaml | kubectl apply -f -

   kubectl -n token-place create secret generic token-place-env \
     --from-literal=NEXTAUTH_SECRET="..." \
     --from-literal=NEXTAUTH_URL="https://relay.token.place"

   kubectl -n dspace create secret generic dspace-env \
     --from-literal=NEXTAUTH_SECRET="..." \
     --from-literal=NEXTAUTH_URL="https://dspace.democratized.space"
   ```
2. Author lightweight values files (commit them to `platform/` or `infra/`):
   ```yaml
   # helm-values/token-place.yaml
   image:
     repository: ghcr.io/futuroptimist/token-place-api
     tag: main
   envFromSecret: token-place-env
   service:
     type: ClusterIP
     port: 5000
   ingress:
     enabled: true
     hosts:
       - host: relay.token.place
         paths:
           - path: /
             pathType: Prefix
   ```

   ```yaml
   # helm-values/dspace.yaml
   image:
     repository: ghcr.io/democratizedspace/dspace
     tag: v3
   envFromSecret: dspace-env
   service:
     type: ClusterIP
     port: 5050
   ingress:
     enabled: true
     hosts:
       - host: app.democratized.space
         paths:
           - path: /
             pathType: Prefix
   ```
3. Install or upgrade the releases. Use `oci://` charts, a private registry, or in-repo charts—this
   example assumes you generated local charts under `platform/charts/`:
   ```bash
   helm upgrade --install token-place ./platform/charts/token-place \
     --namespace token-place --create-namespace \
     --values helm-values/token-place.yaml --wait

   helm upgrade --install dspace ./platform/charts/dspace \
     --namespace dspace --create-namespace \
     --values helm-values/dspace.yaml --wait
   ```
4. Replay application smoke tests from the Pi or your CI harness to confirm the services respond:
   ```bash
   just token-place-samples TOKEN_PLACE_SAMPLE_ARGS="--host relay.token.place"
   ```
5. Feed the releases into `sugarkube-helm-bundles.service` by dropping matching `.env` files under
   `/etc/sugarkube/helm-bundles.d/`. That keeps future cluster reboots or new nodes in sync with your
   production manifests.

## 6. Keep iterating

- Continue with [pi_token_dspace.md](./pi_token_dspace.md) for Cloudflare Tunnel exposure and
  application-specific health checks.
- Use [pi_helm_bundles.md](./pi_helm_bundles.md) to make Helm bundles part of the first boot path so
  token.place and dspace ship alongside the cluster.
- When you're ready for GitOps, run `just flux-bootstrap env=dev` and manage the deployments from the
  `platform/` directory.
- Document regressions in `outages/` immediately—the combination of sanitized `logs/up/` captures and
  outage write-ups keeps the cluster reproducible.
