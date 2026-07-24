# Staging observability Helm runbook

The current live `sugar-staging` observability stack is managed by a guarded, non-Flux Helm lifecycle. The legacy Flux/Longhorn manifests under `platform/observability/kube-prometheus-stack*.yaml` and `clusters/*/patches/kube-prometheus-stack-values.yaml` are inactive, unvalidated future/legacy configuration and must not be applied to staging or production as currently written. Do not combine both lifecycle paths for the same `kube-prometheus-stack` release.

## Prerequisites

- A kubeconfig scoped to staging: `just kubeconfig-env env=staging`.
- Helm and kubectl on PATH.
- The operator-managed Grafana admin Secret already exists in `monitoring` as `grafana-admin-credentials` with chart-supported keys `admin-user` and `admin-password`. Do not print or commit Secret values.
- Production observability is intentionally unsupported in this slice; `prod` and `production` fail before Helm or kubectl mutation.

## Pinned inputs

- Chart: `prometheus-community/kube-prometheus-stack`.
- Chart version pin: `platform/observability/helm/kube-prometheus-stack.version` (`87.19.0`).
- Ordered values: `platform/observability/helm/kube-prometheus-stack.values.common.yaml`, then `clusters/staging/observability/kube-prometheus-stack.values.yaml`.

The values keep Prometheus and Alertmanager ClusterIP-only, disable public ingress, disable Grafana persistence, and expose only Grafana on the LAN NodePort `30300`.

## Read-only preflight and status

```bash
just observability-render env=staging
just observability-status env=staging
just observability-verify env=staging
```

`render` templates the complete pinned chart without applying it. `status` summarizes the Helm release, Prometheus Operator, Prometheus, Grafana, Alertmanager, kube-state-metrics, node-exporter, custom resources, Services, PVCs, CRDs, and the LAN URL. `verify` is read-only and exits nonzero when required CRDs, workloads, PVC state, replica counts, Grafana exposure, or DSPACE ServiceMonitor discovery are not healthy.

## Fresh install

Use only on a fresh staging cluster where the release does not already exist:

```bash
just observability-install env=staging
```

The helper resolves the current context, validates staging identity, renders the chart first, and then runs `helm install` with the pinned version, both values files, `--wait`, and an explicit Pi-appropriate timeout. It fails clearly if the release already exists.

## Steady-state upgrade

Use for the existing live staging release:

```bash
just observability-upgrade env=staging
just observability-verify env=staging
```

The upgrade path renders first, never uses `--reuse-values`, and fails clearly if the release is missing. Keep the previous complete values files and version available for review before changing this pin.

## LAN access and public exposure policy

Grafana is available at `http://sugarkube3.local:30300`; the same NodePort is available through the other staging nodes. Do not add Cloudflare routes, public DNS, Kubernetes Ingress, router forwarding, public Prometheus, public Alertmanager, or public Grafana in this lifecycle.

## Storage and retention

Prometheus uses one replica, retention `7d`, retention size `15GB`, a `local-path` ReadWriteOnce PVC, and a `20Gi` request. The repository does not pin Prometheus to an NVMe node; scheduling remains Kubernetes/storage-class controlled.

## Rollback

Rollback with Helm to the prior revision after confirming the prior chart version and full ordered values chain:

```bash
helm -n monitoring history kube-prometheus-stack
helm -n monitoring rollback kube-prometheus-stack <prior-revision> --wait --timeout 15m
just observability-verify env=staging
```

Do not use `--reuse-values` for forward upgrades; rollback relies on Helm revision history and the previously committed complete inputs.

## Troubleshooting signals

- Context mismatch: the helper prints the requested environment, current context, server, labels, and connected nodes, then fails before mutation.
- Missing CRDs: install/upgrade rendering may succeed, but `observability-verify` reports missing Prometheus Operator CRDs.
- Missing Grafana Secret: create the operator-managed Secret with the expected key names without logging values, then rerun install or upgrade.
- Unbound PVC: check the `monitoring` PVC and `local-path` provisioner; do not patch node affinity into the values.
- Failed workloads: inspect the named Deployment, StatefulSet, or DaemonSet and its events/logs without exposing Secret data.
- DSPACE ServiceMonitor: it must be labeled `release: kube-prometheus-stack` and reference an existing Secret; the verifier checks the reference without printing the Secret value.

## Follow-ups intentionally out of scope

Blackbox exporter installation, Probe resources, dashboards, useful Alertmanager receivers, NetworkPolicies, and central multi-cluster Grafana are separate follow-ups.
