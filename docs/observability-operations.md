# Observability operations runbook

This runbook is the canonical lifecycle for the current live **staging** `kube-prometheus-stack` release. It is a guarded, non-Flux Helm workflow. The older Flux/Longhorn files under `platform/observability/` and `clusters/*/patches/kube-prometheus-stack-values.yaml` are inactive legacy/future configuration and must not be applied to staging or production as currently written. Do not combine Flux reconciliation and these Helm recipes for the same release.

## Prerequisites

- `helm`, `kubectl`, `python3`, `just`, and a readable staging kubeconfig.
- The kubeconfig must identify the connected cluster as staging through the repository's cluster identity guard.
- The `monitoring` namespace must have the operator-managed Grafana admin Secret named `grafana-admin-credentials` before Grafana starts. The pinned chart reads `admin-user` and `admin-password` keys from that Secret. Do not print or commit Secret data.
- The Prometheus Operator CRDs must be installed by the chart for fresh installs and present for steady-state verification.

## Pinned inputs

- Chart: `prometheus-community/kube-prometheus-stack`.
- Version pin: `platform/observability/helm/kube-prometheus-stack.version` (`87.19.0`).
- Ordered values: `platform/observability/helm/kube-prometheus-stack.values.common.yaml`, then `clusters/staging/observability/kube-prometheus-stack.values.yaml`.
- Production values are intentionally not codified in this slice.

## Read-only preflight and status

Run these before any change:

```bash
just kubeconfig-env env=staging
just observability-status env=staging
just observability-render env=staging
```

`env=int` is accepted only as the repository's deprecated alias for staging. Missing, unknown, `prod`, and `production` environments fail with a message that production observability is not yet codified.

## Render, install, and upgrade

`observability-render` templates the complete chart with the pinned version and full ordered values. It does not mutate the cluster.

For a fresh staging cluster, after creating the Grafana Secret without exposing its values:

```bash
just observability-install env=staging
just observability-verify env=staging
```

`observability-install` fails if the release already exists. For steady-state changes to the existing live staging release:

```bash
just observability-render env=staging
just observability-upgrade env=staging
just observability-verify env=staging
```

`observability-upgrade` fails if the release is missing. Neither mutating path uses `--reuse-values`; both render first, use `--wait`, and use an explicit Pi-appropriate timeout.

## Expected staging baseline

Prometheus runs one replica with `7d` retention, `15GB` retention size, a `local-path` `ReadWriteOnce` 20 Gi PVC, 200m CPU request, 512 Mi memory request, 2 Gi memory limit, admin API disabled, and external label `cluster=sugarkube-int`. The PVC must be `Bound`; the values do not pin scheduling to a specific node.

Alertmanager runs one replica with a no-op receiver named the string `"null"`. Grafana persistence and ingress are disabled. Grafana is the only NodePort and is available on the LAN at `http://sugarkube3.local:30300`; the same NodePort is reachable through the other staging nodes. Prometheus, Alertmanager, and other administrative services remain ClusterIP-only. No public DNS, Cloudflare route, router forwarding, or Kubernetes Ingress is part of this lifecycle.

Prometheus discovers ServiceMonitor and Probe resources labeled `release: kube-prometheus-stack`, including the DSPACE ServiceMonitor. The DSPACE ServiceMonitor must reference an existing Secret, but verification prints only the Secret name.

## Verification and troubleshooting

Run:

```bash
just observability-verify env=staging
```

Common failures:

- Context mismatch: rerun `just kubeconfig-env env=staging` and confirm the current context before retrying.
- Missing CRDs: run a fresh install only on a new cluster, or inspect the existing Helm release and CRD ownership before upgrading.
- Unbound PVC or wrong storage class: inspect `kubectl -n monitoring get pvc`; staging expects `Bound` and `local-path`.
- Missing Grafana Secret: create the operator-managed `grafana-admin-credentials` Secret with the expected keys without logging values.
- Failed workloads: inspect `kubectl -n monitoring get deploy,statefulset,daemonset,pods` and Helm status.

When Prometheus is reachable, confirm DSPACE target health through a read-only Prometheus targets query or temporary local port-forward. Do not print bearer tokens or Secret values.

## Rollback

Rollback to the prior Helm revision only after preserving the prior complete chart version and values files used for that revision:

```bash
helm -n monitoring history kube-prometheus-stack
helm -n monitoring rollback kube-prometheus-stack <prior-revision> --wait --timeout 15m
just observability-verify env=staging
```

## Follow-ups

Blackbox exporter expansion, dashboards, useful Alertmanager receivers, NetworkPolicies, and central multi-cluster Grafana are separate follow-ups. Production observability remains intentionally unsupported until a proven live production baseline exists.
