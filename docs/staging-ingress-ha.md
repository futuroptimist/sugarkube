# Staging DNS and public-ingress high availability

## 2026-07-29 node-failure drill record

Before [PR #2400](https://github.com/futuroptimist/sugarkube/pull/2400), staging had one CoreDNS
replica, one Traefik replica, and two Cloudflare Tunnel replicas. A loss of `sugarkube3` caused
roughly six minutes of public token.place interruption. PR #2400 added node-spread CoreDNS coverage
and two node-separated Traefik replicas.

For the post-change drill, an operator manually powered off `sugarkube3` at approximately
`2026-07-29T00:05:25-07:00`. The node became `NotReady`; `sugarkube4` and `sugarkube5` stayed
`Ready`, and Kubernetes API/etcd readiness remained available. Healthchecks detected the missing
node heartbeat and created a PagerDuty incident. Sampled DSPACE, danielsmith.io, and Jobbot3000
endpoints continued to return HTTP 200.

token.place remained on `sugarkube4` with zero restarts. It had the only visible transient: one root
request took about 4.7 seconds, one `/livez` request took about 10 seconds, and one `/healthz`
request returned HTTP 502 after about 10 seconds. Sampled endpoints were normal again by
approximately `00:06:14`, less than 49 seconds after shutdown. The compute client needed roughly
another 10–15 seconds to re-register before chat worked.

EndpointSlices eventually marked dead-node Traefik and CoreDNS endpoints `ready: false`,
`serving: false`, and `terminating: true`; surviving endpoints remained ready and serving. A
replacement Traefik pod later scheduled on `sugarkube5`. After restoration, every node was `Ready`,
CoreDNS had ready endpoints on all three nodes, and Traefik was ready on `sugarkube4` and
`sugarkube5`. Ingress HA, blackbox, Prometheus, Alertmanager, and node-heartbeat verification all
passed, and Healthchecks returned green. The evidence does **not** establish when PagerDuty
auto-resolved, so this record makes no claim about its resolution timing.

> **Evidence limitations:** the sampler was serial and cannot prove zero failures between samples.
> This drill proved continuity of shared ingress and DNS, not fast rescheduling of every singleton
> workload. token.place happened to remain on a surviving node. Treat the observed residual delay
> as an open follow-up in [issue #2407](https://github.com/futuroptimist/sugarkube/issues/2407), not
> as proof of failure-free application HA.

## Current implementation and ownership

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
configuration. Verification requires two healthy CoreDNS endpoints and Traefik pods on distinct
hostnames. It discovers exactly one Cloudflare Tunnel Deployment cluster-wide by the
`app.kubernetes.io/name=cloudflare-tunnel` label, then checks only matching pods in its namespace;
zero or multiple releases fail closed. It never queries tunnel Secrets or logs.

Status and verification aggregate every `discovery.k8s.io/v1` EndpointSlice selected by
`kubernetes.io/service-name=<service>` for `kube-dns` and Traefik. Endpoints are deduplicated by node
name, sorted addresses, and target reference. An endpoint is healthy only when effective `ready`
and `serving` are true and `terminating` is false. Per the EndpointSlice compatibility contract, an
absent `ready` is treated as true, absent `serving` follows effective readiness, and absent
`terminating` is false. Unhealthy endpoints remain in redacted diagnostics but never count as
healthy; summaries are sorted and do not print addresses.

Verification also performs an in-cluster DNS lookup. Public HTTPS targets are discovered from live
Probe resources labeled `environment=staging,criticality=critical`, and at least one is required.
Curl timeouts are bounded, and failures redact the target and curl diagnostics. The temporary DNS
pod is removed on success, error, or signal.

Rollback removes only the two resources owned here and waits for the packaged defaults:

```bash
just staging-ingress-ha-rollback env=staging
just staging-ingress-ha-status env=staging
```

Rollback intentionally returns DNS/ingress to the K3s singleton defaults and therefore removes the
one-node availability guarantee. It does not disable or replace K3s components.

## Manual one-node power-off drill procedure

This is a guarded manual procedure for a future authorized maintenance window. Do not automate a
shutdown, and never remove another node while redundancy is reduced. The operator workstation must
have `rg` (ripgrep) installed for the readiness command below. After apply and verify, run
verification continuously from a different server in its own terminal:

```bash
while true; do just staging-ingress-ha-verify env=staging; sleep 5; done
```

In a second terminal, manually power off exactly one server, observe it, restore it, wait for
readiness, and check the contacted API server's built-in readiness endpoint:

```bash
ssh sugarkube3 'sudo systemctl poweroff'
kubectl get nodes --watch
# Restore power to sugarkube3 using the normal host power procedure.
kubectl wait --for=condition=Ready node/sugarkube3 --timeout=10m
kubectl get --raw='/readyz?verbose' | rg 'etcd|readyz check passed'
```

This default check proves that the contacted API server is ready and that its etcd dependency is
ready. It is **not** a complete per-member etcd health, consistency, or latency report. Deeper
inspection is optional and requires a separately installed, compatible `etcdctl`, configured with
the official K3s-managed endpoint and client-certificate paths. Follow the current K3s
documentation for those paths; do not print certificates, private keys, or Secret contents.

Public endpoints should remain available, subject to the serial-sampling limitation above.
Healthchecks and PagerDuty should still report the intentionally powered-off node; those alerts
prove host monitoring works and are not a reason to suppress it. Do not test another node until
`sugarkube3` is `Ready`, the readiness check passes, and any required optional per-member inspection
confirms recovery.

This baseline is platform/app agnostic. It does not alter eviction or node-monitor timing, scale
applications, or change observability credentials. In particular, token.place relay registration
and default rate-limit state are process-local; token.place application-level HA remains separate
design work.
