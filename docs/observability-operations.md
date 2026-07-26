# Observability operations runbook

This runbook covers the current live **staging-only** kube-prometheus-stack lifecycle. It is intentionally non-Flux: operators use guarded Helm commands from this repository, with the chart version and full values chain committed in Git.

Production observability is intentionally unsupported in this slice because no production live baseline has been proven yet.

## Canonical sources

- Chart version: `platform/observability/helm/kube-prometheus-stack.version` (`87.19.0`).
- Common values: `platform/observability/helm/kube-prometheus-stack.values.common.yaml`.
- Staging overrides: `clusters/staging/observability/kube-prometheus-stack.values.yaml`.
- Staging dashboard: `clusters/staging/observability/dashboards/sugarkube-staging-observability.json`.
- Helper: `scripts/observability_helm.sh` through `just observability-*` recipes.

The repository owns one Helm-provisioned dashboard, **Sugarkube Staging
Observability**, with stable UID `sugarkube-staging-observability`. The helper
passes that standalone JSON to chart `87.19.0` with the Grafana chart's
`grafana.dashboards` file value. The chart renders one ConfigMap mounted at
`/var/lib/grafana/dashboards/sugarkube`, where Grafana's file provider loads it.
This source is shared by render, install, and upgrade; neither Grafana
persistence nor a manual UI save is involved.

The staging blackbox exporter and Probe lifecycle is documented separately in
[Staging blackbox monitoring](observability-blackbox.md). That guarded lifecycle
exclusively owns its narrowly scoped staging Prometheus-to-exporter
NetworkPolicy; it is not part of an active Flux or cluster Kustomize graph.
The observed live baseline had no monitoring default-deny or
`allow-monitoring-ingress` policy. The blackbox policy therefore selects only
the exporter and isolates only ingress to it, allowing the canonical Prometheus
pods to reach TCP 9115. The former egress policy selected Prometheus and was
unsafe because that selection isolated every Prometheus egress path, including
DNS, while permitting only exporter traffic. The corrected policy leaves
Prometheus DNS and all other egress unaffected. The exporter remains
ClusterIP-only.

The old Flux/Longhorn files under `platform/observability/*.yaml` and `clusters/*/patches/kube-prometheus-stack-values.yaml` are inactive, unvalidated future/legacy configuration. They are deliberately absent from the platform resources and cluster overlay patches, so Flux does not reconcile the manually managed release. They must not be applied to staging or production as currently written, and operators must not combine Flux and manual Helm lifecycle paths for the same `kube-prometheus-stack` release.

## Prerequisites

- A working staging kubeconfig whose current context is `sugar-staging`.
- `kubectl`, `helm`, `python3`, and `just` installed locally.
- The `prometheus-community` Helm repository reachable for rendering/install/upgrade.
- Namespace `monitoring` may be absent before a fresh install; the install recipe creates it.
- Operator-managed Grafana admin Secret exists before Grafana starts:
  - Secret name: `grafana-admin-credentials`.
  - Username key: `admin-user`.
  - Password key: `admin-password`.

Never put example credentials or plaintext Secret data in commands, logs, docs, commits, or PRs.

## Read-only preflight and status

```bash
just observability-render env=staging
just observability-status env=staging
just observability-verify env=staging
just observability-dashboard-verify env=staging
```

`env=int` is accepted only through the repository's deprecated alias normalization to `staging`. Missing, unknown, `prod`, and `production` fail before Helm or kubectl mutation with a message that production observability is not yet codified.

Each helper prints the resolved environment, current Kubernetes context, namespace, release, chart, pinned version, ordered values files, and Grafana LAN URL.

## Render, install, and upgrade distinction

- `just observability-render env=staging` renders the complete pinned chart and values chain. It is read-only.
- `just observability-install env=staging` is for a fresh cluster. It renders first, checks the staging context, and fails if the Helm release already exists.
- `just observability-upgrade env=staging` is for steady-state changes. It renders first, checks the staging context, and fails if the Helm release does not exist.

The mutating recipes never use `--reuse-values`; the committed version and both values files are always supplied in order.
The existing staging blackbox exporter release is upgraded after this change
with `just observability-blackbox-upgrade env=staging`; it is not reinstalled.
Repository tests do not perform any live cluster mutation, and repository state
is not rollout evidence.

## Fresh install procedure

1. Select the staging kubeconfig:
   ```bash
   just kubeconfig-env env=staging
   ```
2. Confirm the rendered manifests contain one Prometheus replica, one Alertmanager replica, `local-path` 20 Gi Prometheus storage, Grafana NodePort `30300`, no Grafana Ingress, no Prometheus/Alertmanager NodePort, no Longhorn references, and no embedded credentials:
   ```bash
   just observability-render env=staging
   ```
3. Confirm `grafana-admin-credentials` exists without printing values:
   ```bash
   kubectl -n monitoring get secret grafana-admin-credentials
   ```
4. Install:
   ```bash
   just observability-install env=staging
   ```
5. Verify:
   ```bash
   just observability-verify env=staging
just observability-dashboard-verify env=staging
   ```

## Steady-state upgrade procedure

1. Review changes to the version file and both values files.
2. Render and inspect the full output:
   ```bash
   just observability-render env=staging
   ```
3. Upgrade the existing release:
   ```bash
   just observability-upgrade env=staging
   ```
4. Verify:
   ```bash
   just observability-verify env=staging
just observability-dashboard-verify env=staging
   ```

## Dashboard rollout and acceptance

The dashboard opens on the last six hours and refreshes every 30 seconds. Its
rows cover overall DSPACE and public endpoint status; bounded route and status
class HTTP rates, errors, and latency; runtime memory and build identity; dChat
and token.place dependency activity; and the bounded-label blackbox endpoint,
duration, response-status, and TLS views. The `environment` variable defaults
to staging, while `app` and `route` default to all available bounded values.

dChat and token.place dependency counters are event-driven and may not exist
until relevant traffic occurs. Their queries safely render zero, described as
“no requests observed”; zero is not an instrumentation failure. Use the
separate instrumentation status panel to assess instrumentation health.

`just observability-dashboard-verify env=staging` is a guarded, read-only
check. After rejecting unsupported environments and the wrong cluster, it
temporarily forwards the ClusterIP Grafana service and queries Grafana's API by
the stable dashboard UID. It reads `grafana-admin-credentials` only through an
in-memory pipe, redacts response diagnostics, and cleans up its port-forward
and restricted temporary directory on every exit. It does not mutate Helm or
Kubernetes state. A ConfigMap check alone is not sufficient evidence that
Grafana loaded the dashboard.

Visual inspection remains part of staging acceptance. In addition to running
the verifier, open the LAN-only Grafana UI and confirm useful default data,
panel units, label legends, failure colors, and the TLS warning below 30 days
and critical range below 7 days.

### Post-merge operator checklist

```bash
cd ~/sugarkube
git status --short
git pull --ff-only
just kubeconfig-env env=staging

just observability-render env=staging \
  >/tmp/kube-prometheus-stack.dashboard.rendered.yaml

just observability-upgrade env=staging
just observability-verify env=staging
just observability-dashboard-verify env=staging
just observability-blackbox-verify env=staging

# Restart the single Grafana pod, wait for rollout, and prove that the
# Helm-provisioned dashboard reappears without manual UI changes.
kubectl -n monitoring delete pod \
  -l 'app.kubernetes.io/name=grafana,app.kubernetes.io/instance=kube-prometheus-stack'

kubectl -n monitoring rollout status \
  deployment/kube-prometheus-stack-grafana \
  --timeout=20m

just observability-dashboard-verify env=staging
```

The final API verification after pod replacement proves file reprovisioning
works despite disabled Grafana persistence. Perform these live commands only
as a staging operator after merge; repository validation does not contact the
cluster. Roll back with the existing Helm revision procedure below, then restore
the prior complete Git sources before the next forward upgrade.

## Runtime expectations

- Helm release: `kube-prometheus-stack` in namespace `monitoring`.
- Prometheus: one replica, `7d` retention, `15GB` retention size, `local-path` `ReadWriteOnce` PVC requesting `20Gi`, CPU request `200m`, memory request `512Mi`, memory limit `2Gi`, admin API disabled, and external label `cluster=sugarkube-int`.
- Alertmanager: one replica and no-op receiver named exactly `"null"`.
- Grafana: persistence disabled, no Ingress, LAN-only NodePort `30300`.
- Grafana URL: `http://sugarkube3.local:30300`; the same NodePort is available through the other staging nodes.
- Prometheus, Alertmanager, and administrative services remain ClusterIP-only.
- No public ingress, public DNS, Cloudflare route, router forwarding, or public observability endpoint is part of this lifecycle.
- Verification waits up to the configured Helm timeout for each workload and requires every desired node-exporter pod to be ready. After workload readiness, it also waits for DSPACE target discovery and the first successful scrape. By default, it schedules 20 observations 15 seconds apart and gives each proxy request a finite 14-second budget, so the final request finishes within a 299-second overall deadline. Request time consumes the cadence delay rather than extending it. Override the positive-integer settings with `SUGARKUBE_OBSERVABILITY_TARGET_HEALTH_INTERVAL_SECONDS` and `SUGARKUBE_OBSERVABILITY_TARGET_HEALTH_ATTEMPTS`; the request budget and deadline are derived from those controls. Missing, unknown, down, and partially healthy target sets are retried, but Kubernetes transport failures, invalid UTF-8, malformed JSON, non-string target health, invalid Prometheus response structures, and unsuccessful Prometheus API statuses fail immediately.

## Troubleshooting signals

- **Context mismatch:** helper exits before mutation and prints the expected `sugar-staging` context. Rerun `just kubeconfig-env env=staging`.
- **Missing CRDs:** `observability-verify` fails on Prometheus Operator CRD checks; render/install/upgrade the pinned chart rather than applying Flux CRDs manually.
- **Unbound PVC:** verify `kubectl -n monitoring get pvc` shows `Bound` and storage class `local-path`; investigate local-path provisioner and node disk health without pinning Prometheus to a node in Git.
- **Missing Grafana Secret:** create or repair the operator-managed `grafana-admin-credentials` Secret out of band without committing values.
- **Failed workloads:** use `just observability-status env=staging`, `kubectl -n monitoring describe`, and pod logs to identify image pulls, scheduling, resources, or PVC failures.

## Rollback

Use Helm rollback to the prior known-good revision, then restore the prior complete Git values/version before the next upgrade attempt:

```bash
helm -n monitoring history kube-prometheus-stack
helm -n monitoring rollback kube-prometheus-stack <prior-revision> --wait --timeout 20m
just observability-verify env=staging
just observability-dashboard-verify env=staging
```

Do not use `--reuse-values` for the next forward upgrade; commit the full intended version and values chain first.

## Follow-ups intentionally out of scope

Additional dashboards, useful Alertmanager receivers, Grafana persistence,
central multi-cluster Grafana, and production observability codification are
separate follow-ups. The existing staging blackbox ingress-only NetworkPolicy
remains owned by its separate lifecycle and is unchanged by dashboard rollout.
