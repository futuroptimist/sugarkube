# Staging DNS and public-ingress high availability

## Incident and ownership

Before PR #2400, staging had one CoreDNS replica, one Traefik replica, and two Cloudflare Tunnel
replicas. When `sugarkube3` was powered off, the other two `control-plane,etcd` servers retained the
two-member majority of the three-member etcd cluster, so etcd and the API remained available.
Public token.place service nevertheless failed for about six minutes: the sole packaged CoreDNS pod
was on the lost node. Kubernetes waited its default roughly five-minute `NodeNotReady` eviction
interval before `TaintManagerEviction` replaced it; the application itself remained running on
`sugarkube4`.

The active staging lifecycle is deliberately non-Flux:

* K3s owns the packaged `coredns` Deployment, `kube-dns` Service, Corefile, RBAC, service account,
  probes, and image. This lifecycle clones that live pod template into the narrowly owned,
  two-replica `coredns-ha` companion. Required hostname anti-affinity includes all `kube-dns` pods.
  Thus it preserves the exact installed K3s compatibility surface, adds endpoints before any other
  change, and never edits `/var/lib/rancher/k3s/server/manifests` or fights the packaged Deployment.
* K3s owns packaged Traefik. The committed `HelmChartConfig` is K3s's supported merge point and adds
  two replicas with required hostname anti-affinity without replacing existing chart values,
  ServiceLB, ports, ingress classes, or TLS configuration.
  Both lifecycle resources carry `sugarkube.dev/managed-by: staging-ingress-ha`. Apply and rollback
  inspect only that ownership label and refuse to overwrite or delete a resource with another owner.
  If a `kube-system/traefik` HelmChartConfig already exists, first review and redact its values,
  merge them into this file, and arrange ownership; this lifecycle never replaces unknown values.
* The active token-mode Cloudflare release is discovered cluster-wide by stable
  `app.kubernetes.io/name=cloudflare-tunnel` labels. Its observed namespace is `cloudflare`, and its
  two ready, node-spread pods are already HA. This lifecycle verifies but neither installs nor reads
  its Secret.

The `platform/cloudflared` HelmRelease and `clusters/staging/patches/cloudflared-values.yaml` belong
to the inactive future/legacy Flux graph; they are not the source of truth for this live release and
must not be applied alongside it. The durable active sources are
`clusters/staging/ingress-ha/traefik-helmchartconfig.yaml` and
`scripts/staging_ingress_ha.sh`. Re-running apply is idempotent; K3s/server restarts retain the
companion Deployment and reconcile the HelmChartConfig.

PR #2400 deployed this node-spread CoreDNS coverage and two node-separated Traefik replicas. The
current staging topology is therefore no longer singleton for either shared component. See the
[dated 2026-07-29 drill record](drills/2026-07-29-staging-node-failure.md) for the resulting evidence,
conclusions, and limitations.

## Post-merge rollout and rollback

Use a kubeconfig whose context is exactly `sugar-staging`. Render/status are read-only. Apply,
upgrade, verify, and rollback fail closed for every environment except staging and for every other
context. Verification creates a temporary DNS probe pod, so it receives the same exact-context
guard as the other mutating commands. Rollout waits are bounded at 180 seconds by default.

```bash
just staging-ingress-ha-render env=staging
just staging-ingress-ha-status env=staging
just staging-ingress-ha-apply env=staging
just staging-ingress-ha-verify env=staging
```

Apply first creates two ready CoreDNS companion endpoints and only then applies Traefik's supported
configuration. Verification requires two ready CoreDNS and Traefik pods on distinct hostnames. It
discovers exactly one Cloudflare tunnel Deployment cluster-wide by the
`app.kubernetes.io/name=cloudflare-tunnel` label, then checks only matching pods in its namespace;
zero or multiple releases fail closed. It never queries tunnel Secrets or logs. Verification also
aggregates every `discovery.k8s.io/v1` EndpointSlice selected by
`kubernetes.io/service-name` for `kube-dns` and Traefik, checks healthy Service backends, and runs an
in-cluster DNS lookup. Exact duplicate endpoints are deterministically collapsed across slices.
An endpoint is healthy only when ready and serving and not terminating. Per the EndpointSlice API
compatibility contract, absent `ready` means ready, absent `serving` follows `ready`, and absent
`terminating` means non-terminating. Unhealthy endpoints are diagnosed but never counted. Public
HTTPS targets are discovered from live Probe resources labeled
`environment=staging,criticality=critical`, and at least one is required. Curl timeouts are bounded,
and failures redact the target and curl diagnostics. The temporary DNS pod is removed on success,
error, or signal.

Rollback removes only the two resources owned here and waits for the packaged defaults:

```bash
just staging-ingress-ha-rollback env=staging
just staging-ingress-ha-status env=staging
```

Rollback intentionally returns DNS/ingress to the K3s singleton defaults and therefore removes the
one-node availability guarantee. It does not disable or replace K3s components.

## One-node power-off drill

After apply and verify, run verification continuously from a different server in its own terminal:

```bash
while true; do just staging-ingress-ha-verify env=staging; sleep 5; done
```

In a second terminal, power off exactly one server, observe it, restore it, wait for readiness, and
check API/etcd readiness:

```bash
ssh sugarkube3 'sudo systemctl poweroff'
kubectl get nodes --watch
# Restore power to sugarkube3 using the normal host power procedure.
kubectl wait --for=condition=Ready node/sugarkube3 --timeout=10m
kubectl get --raw='/readyz?verbose' | rg 'etcd|readyz check passed'
```

Public endpoints should remain continuously available. Healthchecks.io and PagerDuty should still
report the intentionally powered-off node; those alerts prove host monitoring works and are not a
reason to suppress it. Do not test another node until `sugarkube3` is `Ready` **and** the command
above confirms the contacted API server and its etcd dependency are ready. This is not a complete
per-member etcd health, consistency, or latency report. Deeper inspection is optional and requires
a separately installed compatible `etcdctl`, configured with official K3s-managed endpoints and
client-certificate paths without printing certificate or key contents. Never remove a second server
while etcd redundancy is reduced.

This baseline is platform/app agnostic. It does not alter eviction or node-monitor timing, scale
applications, or change observability credentials. In particular, token.place relay registration
and default rate-limit state are process-local; token.place application-level HA remains separate
design work.
