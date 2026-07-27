# Observability operations runbook

This runbook covers the current live **staging-only** kube-prometheus-stack lifecycle. It is intentionally non-Flux: operators use guarded Helm commands from this repository, with the chart version and full values chain committed in Git.

Production observability is intentionally unsupported in this slice because no production live baseline has been proven yet.

## Canonical sources

- Chart version: `platform/observability/helm/kube-prometheus-stack.version` (`87.19.0`).
- Common values: `platform/observability/helm/kube-prometheus-stack.values.common.yaml`.
- Staging overrides: `clusters/staging/observability/kube-prometheus-stack.values.yaml`.
- Staging dashboard: `clusters/staging/observability/dashboards/sugarkube-staging-observability.json`.
- Helper: `scripts/observability_helm.sh` through `just observability-*` recipes.

The dashboard is owned by Sugarkube and provisioned by the pinned Grafana
subchart. Every render, install, and upgrade passes the same standalone JSON
with Helm `--set-file`; the provider mounts it under
`/var/lib/grafana/dashboards/sugarkube`. Its title is **Sugarkube Staging
Observability** and its stable UID is `sugarkube-staging-observability`.
Grafana's chart-rendered Prometheus datasource has stable UID `prometheus`,
which the dashboard references directly.

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

The mutating recipes never use `--reuse-values`; the committed version, both
values files in order, and the dashboard source are always supplied. Before
cluster access or mutation, the helper rejects malformed dashboard JSON,
changed identity, duplicate panel IDs, missing metric families, unsafe
event-driven queries, or invalid datasource references. It then validates that
the pinned render contains exactly one copy in the intended Grafana provider.
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

## Runtime expectations

- Helm release: `kube-prometheus-stack` in namespace `monitoring`.
- Prometheus: one replica, `7d` retention, `15GB` retention size, `local-path` `ReadWriteOnce` PVC requesting `20Gi`, CPU request `200m`, memory request `512Mi`, memory limit `2Gi`, admin API disabled, and external label `cluster=sugarkube-int`.
- Alertmanager: one replica and no-op receiver named exactly `"null"`.
- Grafana: persistence disabled, no Ingress, LAN-only NodePort `30300`.
- The provisioned dashboard defaults to six hours and a 30-second refresh. It
  covers overall DSPACE and public-probe status, bounded DSPACE HTTP rate/error/
  latency, runtime and build identity, feature traffic, and blackbox endpoint,
  duration, HTTP status, and TLS lifetime views. Its staging `environment`,
  `app`, and `route` variables avoid raw target URLs.
- dChat and token.place dependency traffic may be absent until those features
  receive requests. Their queries deliberately fall back to zero: **no requests
  observed** is expected and is not an instrumentation failure.
- Grafana URL: `http://sugarkube3.local:30300`; the same NodePort is available through the other staging nodes.
- Prometheus, Alertmanager, and administrative services remain ClusterIP-only.
- No public ingress, public DNS, Cloudflare route, router forwarding, or public observability endpoint is part of this lifecycle.
- Verification waits up to the configured Helm timeout for each workload and requires every desired node-exporter pod to be ready. After workload readiness, it also waits for DSPACE target discovery and the first successful scrape. By default, it schedules 20 observations 15 seconds apart and gives each proxy request a finite 14-second budget, so the final request finishes within a 299-second overall deadline. Request time consumes the cadence delay rather than extending it. Override the positive-integer settings with `SUGARKUBE_OBSERVABILITY_TARGET_HEALTH_INTERVAL_SECONDS` and `SUGARKUBE_OBSERVABILITY_TARGET_HEALTH_ATTEMPTS`; the request budget and deadline are derived from those controls. Missing, unknown, down, and partially healthy target sets are retried, but Kubernetes transport failures, invalid UTF-8, malformed JSON, non-string target health, invalid Prometheus response structures, and unsuccessful Prometheus API statuses fail immediately.

## Troubleshooting signals

- **Context mismatch:** helper exits before mutation and prints the expected `sugar-staging` context. Rerun `just kubeconfig-env env=staging`.
- **Missing CRDs:** `observability-verify` fails on Prometheus Operator CRD checks; render/install/upgrade the pinned chart rather than applying Flux CRDs manually.
- **Unbound PVC:** verify `kubectl -n monitoring get pvc` shows `Bound` and storage class `local-path`; investigate local-path provisioner and node disk health without pinning Prometheus to a node in Git.
- **Missing Grafana Secret:** create or repair the operator-managed `grafana-admin-credentials` Secret out of band without committing values.
- **Dashboard API verification:** `just observability-dashboard-verify
  env=staging` checks the stable UID through Grafana's API. It validates context
  and cluster identity first, reads the existing Secret without printing it,
  uses a mode-`0600` temporary netrc, and asks this invocation's `kubectl` to
  bind an ephemeral `127.0.0.1` port. The right side of `kubectl`'s forwarding
  message is the resolved pod/container port, so it may differ from the Grafana
  Service port `80`. Authentication begins only after that child reports the
  exact owned forwarding endpoint with valid local and resolved port numbers.
  Success, failure, and interruption all terminate and wait for the child and
  remove the netrc and temporary directory. HTTP 401/403 responses fail
  immediately with redacted diagnostics; only connection and readiness
  failures are retried. It performs no Helm or Kubernetes mutation. A ConfigMap
  check alone is not acceptance evidence.
- **Failed workloads:** use `just observability-status env=staging`, `kubectl -n monitoring describe`, and pod logs to identify image pulls, scheduling, resources, or PVC failures.

## Rollback

Use Helm rollback to the prior known-good revision, then restore the prior complete Git values/version before the next upgrade attempt:

```bash
helm -n monitoring history kube-prometheus-stack
helm -n monitoring rollback kube-prometheus-stack <prior-revision> --wait --timeout 20m
just observability-verify env=staging
# Run this only when <prior-revision> already provisioned the dashboard.
just observability-dashboard-verify env=staging
```

If `<prior-revision>` predates the first dashboard-as-code rollout, a missing
dashboard is the expected rollback state: omit `observability-dashboard-verify`
and use the general `observability-verify` result as acceptance evidence.

Do not use `--reuse-values` for the next forward upgrade; commit the full intended version and values chain first.

## Reprovisioning proof and post-merge checklist

Visual inspection of every panel, variable default, unit, mapping, and threshold
remains part of staging acceptance. Prove that code provisioning, rather than
Grafana persistence or a manual UI save, owns the dashboard by restarting the
single Grafana pod and querying the API again:

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

For rollback, use the existing Helm rollback procedure above. The prior Helm
revision restores its dashboard ConfigMap; after a forward fix, the standard
upgrade lifecycle again supplies the complete values chain and dashboard file.

## Follow-ups intentionally out of scope

Additional dashboards, useful Alertmanager receivers, Grafana persistence,
central multi-cluster Grafana, and production observability codification are
separate follow-ups. The existing blackbox NetworkPolicy is unchanged.
