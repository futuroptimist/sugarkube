# Staging DNS and public-ingress high availability

## Incident and ownership

When `sugarkube3` was powered off, the other two `control-plane,etcd` servers retained the
two-member majority of the three-member etcd cluster, so etcd and the API remained available.
Public service nevertheless failed for about six minutes: the sole packaged CoreDNS pod was on the
lost node. Kubernetes waited its default roughly five-minute `NodeNotReady` eviction interval before
`TaintManagerEviction` replaced it; the application itself remained running on `sugarkube4`.

The active staging lifecycle is deliberately non-Flux:

* K3s owns the packaged `coredns` Deployment, `kube-dns` Service, Corefile, RBAC, service account,
  probes, and image. This lifecycle clones that live pod template into the narrowly owned,
  two-replica `coredns-ha` companion. Required hostname anti-affinity includes all `kube-dns` pods.
  Thus it preserves the exact installed K3s compatibility surface, adds endpoints before any other
  change, and never edits `/var/lib/rancher/k3s/server/manifests` or fights the packaged Deployment.
* K3s owns packaged Traefik. The committed `HelmChartConfig` is K3s's supported merge point and adds
  two replicas with required hostname anti-affinity without replacing existing chart values,
  ServiceLB, ports, ingress classes, or TLS configuration.
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
configuration. Verification requires two ready CoreDNS, Traefik, and Cloudflare connector pods on
distinct hostnames; ready `kube-dns` and Traefik Service backends; an in-cluster DNS lookup; and the
public staging token.place and Democratized Space health endpoints. Override
`SUGARKUBE_STAGING_HEALTH_URLS` only to supply a space-separated, app-agnostic staging endpoint set.
The temporary DNS pod is removed on success, error, or signal.

Rollback removes only the two resources owned here and waits for the packaged defaults:

```bash
just staging-ingress-ha-rollback env=staging
just staging-ingress-ha-status env=staging
```

Rollback intentionally returns DNS/ingress to the K3s singleton defaults and therefore removes the
one-node availability guarantee. It does not disable or replace K3s components.

## One-node power-off drill

After apply and verify, power off exactly one server (for example `sugarkube3`) using the normal
host power procedure, then continuously verify from a different server:

```bash
just staging-ingress-ha-verify env=staging
watch -n 5 'curl -fsS https://staging.token.place/healthz >/dev/null && echo reachable'
```

Public endpoints should remain continuously available. Healthchecks.io and PagerDuty should still
report the intentionally powered-off node; those alerts prove host monitoring works and are not a
reason to suppress it. Restore that node, wait for `kubectl get node sugarkube3` to report `Ready`,
and confirm all three etcd members are healthy **before testing another node**. Never remove a
second server while etcd redundancy is reduced.

This baseline is platform/app agnostic. It does not alter eviction or node-monitor timing, scale
applications, or change observability credentials. In particular, token.place relay registration
and default rate-limit state are process-local; token.place application-level HA remains separate
design work.
