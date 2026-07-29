# Staging DNS and ingress high availability

This is the canonical operations lifecycle for the staging public data path. It
does not make any application highly available.

## Incident and ownership audit

During the controlled shutdown of `sugarkube3`, the remaining two etcd/server
members retained quorum, so the Kubernetes API stayed available. The public path
still failed for about six minutes because the sole CoreDNS pod was on the powered
off node. Kubernetes' default `NoExecute` toleration delayed
`TaintManagerEviction` for approximately five minutes. A replacement CoreDNS pod
then started on `sugarkube4`, and public service recovered immediately. This was
a singleton data-plane dependency failure, not slow etcd quorum formation.

Staging has three distinct ownership paths:

* K3s owns its packaged CoreDNS and Traefik `HelmChart` resources. K3s rewrites
  the packaged manifests at server startup. Traefik uses the supported, version-controlled `HelmChartConfig` in
  `clusters/staging/ingress-ha/`. CoreDNS is not a Helm chart in the active K3s
  lifecycle, so apply clones the live packaged Deployment into a separately named
  supplemental `coredns-ha` Deployment. The clone retains its image, arguments,
  Corefile mount, RBAC, service account, probes, and `kube-dns` selector while
  adding two replicas and required hostname anti-affinity. K3s continues owning
  the original Deployment, so no controllers fight and there is no staged DNS
  gap. Traefik retains LoadBalancer/ServiceLB, ports, classes, TLS, and defaults.
* The active Cloudflare connector is the existing Helm-managed Deployment in
  namespace `cloudflare`, discovered using the stable
  `app.kubernetes.io/name=cloudflare-tunnel` label. Its two ready connectors on
  different nodes are already HA; this lifecycle only verifies them and never
  reads their Secret or installs another Deployment.
* `platform/cloudflared/` and the broad `clusters/*` Flux overlays describe a
  legacy/future `cloudflared` namespace path and are not the active staging
  tunnel lifecycle. Do not apply that path to staging. Likewise, manual
  `kubectl scale`, patches, and edits below
  `/var/lib/rancher/k3s/server/manifests` are ephemeral and unsupported.

Apply refuses to overwrite a pre-existing Traefik `HelmChartConfig` without Sugarkube's
ownership label. This prevents two controllers from fighting and protects live
custom values until they are reviewed and merged into the canonical files.

## Apply and verify after merge

```bash
just kubeconfig-env env=staging
test "$(kubectl config current-context)" = sugar-staging
just staging-ingress-ha-render env=staging
just staging-ingress-ha-status env=staging
just staging-ingress-ha-apply env=staging
just staging-ingress-ha-verify env=staging
```

Render is local and non-mutating. Status is read-only. Verify only creates a
temporary `default/sugarkube-dns-check-*` pod and always deletes it, including
after failure. Mutations require explicit `staging`, exact `sugar-staging`
context, and the staging identity check. Waits default to five minutes. Errors
redact endpoint URLs and never inspect or print tunnel credentials.

Verification proves two ready, hostname-spread pods for each of CoreDNS, Traefik,
and the existing tunnel; ready `kube-dns` and Traefik Service backends; DNS from
a temporary pod; and all environment-labeled staging public Probe targets.

## Rollback

```bash
just staging-ingress-ha-rollback env=staging
just staging-ingress-ha-status env=staging
```

Rollback deletes only the owned supplemental `coredns-ha` Deployment and Traefik
`HelmChartConfig`, then waits for the packaged workloads. It never deletes Services,
RBAC, CoreDNS configuration, Traefik, or the tunnel. Rollback intentionally
removes the HA guarantee.

## One-node power-off drill

After apply and verify, power off exactly one server using the normal hardware
procedure. From an unaffected operator host, continuously exercise a public
health endpoint and verify:

```bash
watch -n 2 'kubectl --context sugar-staging get nodes; curl --fail --silent --show-error --max-time 10 https://staging.token.place/healthz >/dev/null'
just staging-ingress-ha-verify env=staging
```

The example URL is an operator drill target, not embedded platform configuration.
Public endpoints should remain continuously available while Healthchecks.io and
PagerDuty still report the powered-off node. Bring it back before another test.
**Do not power off another node until the first is `Ready` and etcd has restored
three-member redundancy.** Then rerun status and verify. Do not tune cluster-wide
node-monitor or default eviction timing for this drill.

The token.place process remains a singleton: relay registration and default
rate-limit state are process-local. Application-level horizontal HA and state
coordination are separate work; no application chart is changed here.
