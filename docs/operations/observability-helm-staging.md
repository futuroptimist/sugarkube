# Staging observability Helm runbook

This runbook is canonical for the current live `sugar-staging` kube-prometheus-stack. It manages Helm directly through guarded `just observability-*` recipes, not Flux. The legacy Flux/Longhorn manifests under `platform/observability/` and `clusters/*/patches/kube-prometheus-stack-values.yaml` are inactive, unvalidated future/legacy configuration; do not apply them to staging or production as currently written, and never combine Flux and non-Flux lifecycle paths for the same Helm release.

Production observability is intentionally unsupported in this slice because there is no proven live production baseline yet.

## Prerequisites

- `kubectl`, `helm`, `just`, Python 3, and access to the `sugar-staging` Kubernetes context.
- A readable kubeconfig prepared with `just kubeconfig-env env=staging`.
- The `monitoring` namespace may be created by Helm on fresh install.
- The operator-managed Grafana admin Secret must already exist before Grafana can become ready:
  - Secret name: `grafana-admin-credentials`
  - username key: `admin-user`
  - Grafana chart credential field: see the common values file for the exact key name
- Do not print, render, commit, or paste the Secret values.

## Pinned chart and values

- Chart: `prometheus-community/kube-prometheus-stack`
- Version pin: `platform/observability/helm/kube-prometheus-stack.version`
- Common values: `platform/observability/helm/kube-prometheus-stack.values.common.yaml`
- Staging values: `clusters/staging/observability/kube-prometheus-stack.values.yaml`

The values chain preserves ServiceMonitor, PodMonitor, Probe, and rule discovery for resources labeled `release: kube-prometheus-stack`, including the DSPACE ServiceMonitor.

## Read-only preflight and status

```bash
just observability-render env=staging
just observability-status env=staging
just observability-verify env=staging
```

`render` contacts Helm chart sources and renders YAML only; it does not install, upgrade, or apply. `status` and `verify` use read-only Helm and kubectl queries.

## Fresh install

Run this only when the release is absent:

```bash
just observability-install env=staging
```

The helper fails if the current context is not `sugar-staging`, if cluster node labels do not identify staging, if rendering fails, or if the Helm release already exists.

## Steady-state upgrade

Run this only when the release already exists:

```bash
just observability-upgrade env=staging
```

The helper renders the pinned chart and complete ordered values first, never uses `--reuse-values`, and then runs `helm upgrade --wait --timeout 20m`. It fails if the release is absent.

## Access policy

Grafana is LAN-only at:

```text
http://sugarkube3.local:30300
```

The same NodePort is available through the other staging nodes. Do not add public ingress, Cloudflare routes, DNS forwarding, or router port forwards for Grafana. Prometheus, Alertmanager, and administrative services remain ClusterIP-only.

## PVC and retention expectations

Prometheus runs one replica with `7d` retention, `15GB` retention size, and a `20Gi` `local-path` PVC. The values must not pin Prometheus to a specific node, even if the current live PVC resides on NVMe-backed storage.

## Rollback

Prefer Helm rollback to a known-good prior revision:

```bash
helm -n monitoring history kube-prometheus-stack
helm -n monitoring rollback kube-prometheus-stack <prior-revision> --wait --timeout 20m
```

For a chart or values rollback, restore the prior committed complete values chain and version pin, render it, and use the distinct upgrade flow. Do not use `--reuse-values`.

## Troubleshooting signals

- Context mismatch: the helper reports the current context and expects `sugar-staging`; run `just kubeconfig-env env=staging` or fix `KUBECONFIG`.
- Missing CRDs: `observability-verify` fails while checking Prometheus Operator CRDs; inspect the Helm release and operator logs.
- Unbound PVC: verify the Prometheus PVC is `Bound` and uses `local-path`; check local-path provisioner health and node storage.
- Missing Grafana Secret: Grafana pods will not become ready until `grafana-admin-credentials` exists with the documented admin credential keys.
- Failed workloads: use `just observability-status env=staging`, then inspect the failing Deployment, StatefulSet, DaemonSet, or pod events.
- DSPACE target issues: verify the ServiceMonitor is labeled `release: kube-prometheus-stack` and references an existing Secret. Do not print the Secret value.

## Follow-ups intentionally out of scope

Blackbox exporter installation, Probe application, dashboards, useful Alertmanager receivers, NetworkPolicies, central multi-cluster Grafana, and production observability values remain separate follow-ups.
