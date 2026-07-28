# Observability operations runbook

This runbook covers the current live **staging-only** kube-prometheus-stack lifecycle. It is intentionally non-Flux: operators use guarded Helm commands from this repository, with the chart version and full values chain committed in Git.

Production observability is intentionally unsupported in this slice because no production live baseline has been proven yet.

## Canonical sources

- Chart version: `platform/observability/helm/kube-prometheus-stack.version` (`87.19.0`).
- Common values: `platform/observability/helm/kube-prometheus-stack.values.common.yaml`.
- Staging overrides: `clusters/staging/observability/kube-prometheus-stack.values.yaml`.
- Staging dashboard: `clusters/staging/observability/dashboards/sugarkube-staging-observability.json`.
- Helper: `scripts/observability_helm.sh` through `just observability-*` recipes.
- Alert delivery, routing, and drill strategy: [`docs/observability-alerting.md`](observability-alerting.md) — this runbook covers deploying and verifying the stack, not how (or whether) it pages anyone yet.

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
- The staging PagerDuty Events API v2 routing key is stored only in
  `monitoring/alertmanager-pagerduty`, under the `routing-key` key. Install and
  upgrade fail closed when that contract is absent or empty; rendering remains offline.

Never put example credentials or plaintext Secret data in commands, logs, docs, commits, or PRs.

## PagerDuty synthetic delivery drill

Repository support does not prove that this configuration is deployed or that a phone receives an
event. The following is an explicitly operator-run staging drill; none of the commands that fire or
resolve it run from CI, rendering, installation, upgrade, status, or verification.

### Create or rotate the credential

Use a hidden read and stream the value directly to `kubectl`. This keeps it out of shell history,
process arguments, generated files, and command output. Run this from a trusted terminal after
selecting the `sugar-staging` context:

```bash
read -r -s -p 'PagerDuty routing key: ' PAGERDUTY_ROUTING_KEY; printf '\n'
printf '%s' "$PAGERDUTY_ROUTING_KEY" |
  kubectl -n monitoring create secret generic alertmanager-pagerduty \
    --from-file=routing-key=/dev/stdin --dry-run=client -o yaml |
  kubectl apply -f -
unset PAGERDUTY_ROUTING_KEY
```

Do not enable shell tracing. Do not inspect the Secret with YAML/JSON output. For rotation, repeat
the same pipeline with the replacement key, wait for the Operator-managed Alertmanager pods to
reload or restart successfully, then repeat the fire/resolve drill below. Keep the old PagerDuty
integration usable until post-rotation verification succeeds, when the provider permits that.

### Render, upgrade, and verify

1. Render offline and inspect only the Alertmanager resource and generated configuration. Confirm
   the root receiver is `"null"`, the Alertmanager Secret list contains
   `alertmanager-pagerduty`, and the only PagerDuty route has the four exact synthetic matchers.
   Confirm the receiver uses
   `/etc/alertmanager/secrets/alertmanager-pagerduty/routing-key` and `send_resolved: true`:

   ```bash
   just observability-render env=staging > /tmp/sugarkube-observability-render.yaml
   less /tmp/sugarkube-observability-render.yaml
   rm -f /tmp/sugarkube-observability-render.yaml
   ```

   The temporary render contains no credential, but remove it after review to avoid stale generated
   artifacts.
2. Apply and verify the canonical release:

   ```bash
   just observability-upgrade env=staging
   just observability-verify env=staging
   ```

   The upgrade preflight checks only the fixed Secret/key contract and never returns its value. The
   verification checks the live Alertmanager custom resource and generated configuration without
   printing either response.
3. Fire the bounded synthetic event explicitly:

   ```bash
   just observability-pagerduty-test env=staging action=fire
   ```

   Manually confirm PagerDuty receipt and phone notification, and acknowledge the incident. The
   helper reports only API success or failure; it cannot prove phone delivery.
4. Resolve the same alert fingerprint explicitly:

   ```bash
   just observability-pagerduty-test env=staging action=resolve
   ```

   Manually confirm that PagerDuty marks the same incident resolved. Fire has a 15-minute `endsAt`
   safety bound; resolve submits the identical complete labels with an immediate `endsAt`.

### Rollback and Secret ordering

If necessary, identify the prior revision with `helm -n monitoring history kube-prometheus-stack`
and use the repository's established Helm rollback procedure for that revision. Verify the stack
again after rollback. **Do not delete `monitoring/alertmanager-pagerduty` before rolling back the
configuration that mounts it.** A missing referenced Secret can prevent Alertmanager pods from
starting, including during rollback. First roll back and verify that the resulting Alertmanager no
longer references the Secret; only then remove an obsolete credential. During rotation, retain the
Secret name and key, update its value through stdin, verify workload health, and repeat both manual
delivery observations before retiring the old provider-side credential.

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
- Alertmanager: one replica and no-op receiver named exactly `"null"`. No real notification receiver (PagerDuty, Healthchecks.io, or otherwise) is configured yet; see [`docs/observability-alerting.md`](observability-alerting.md) for the planned rollout.
- Grafana: persistence disabled, no Ingress, LAN-only NodePort `30300`.
- The provisioned dashboard defaults to six hours and a 30-second refresh. Its
  top-level public availability summary reports **Healthy endpoints**, **Failed
  endpoints**, and a yellow **Missing probe data** count for the selected probe
  filters. Healthy and failed are current `probe_success` results; missing compares
  current samples with lifecycle-owned targets discovered through `up` during the
  seven-day Prometheus retention horizon, so disappeared discovery targets remain
  visible throughout retained history. Exact long-term target inventory remains
  verified by `just observability-blackbox-verify env=staging`.
  `16/0/0` is fully healthy, `15/1/0` has one observed failure, and `15/0/1`
  identifies one expected target without current probe data. If no expected target
  data exists, all three values remain `NO DATA` rather than implying health. The
  detailed endpoint matrix remains the diagnostic view. DSPACE user
  request rate excludes `/healthz`, `/livez`, and
  `/metrics`, whose traffic has a separate operational-rate panel. Status-class
  distribution is an instant categorical summary over the selected time window.
  The `Probe application` and `Probe route` controls filter blackbox panels while
  preserving the internal bounded `app` and `route` labels and avoiding raw
  target URLs. Runtime, build identity, feature traffic, latency, error ratio,
  probe duration, HTTP status, and TLS lifetime views remain available.
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
  bind an ephemeral `127.0.0.1` port. Authentication begins only after that
  child reports the exact owned forwarding endpoint. The right side of
  kubectl's forwarding message is the resolved pod/container port, so it may
  differ from the requested Service port `80`. Success, failure, and
  interruption all terminate and wait for the child and remove the netrc and
  temporary directory. HTTP 401/403 responses fail immediately with redacted
  diagnostics; only connection and readiness failures are retried. It performs
  no Helm or Kubernetes mutation. A ConfigMap check alone is not acceptance
  evidence.
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

## Manually verified staging observations

The reprovisioning proof above is scripted and repeatable: `observability-dashboard-verify` is the
acceptance evidence, and it runs the same way every time. The following two observations are not
scripted or CI-enforced today — they are operator-recorded manual checks, noted here so they aren't
lost, and distinct from the automated evidence above:

- **Prometheus data/target continuity across a pod restart.** Operators have manually restarted the
  single Prometheus pod in staging and confirmed that retained series and target discovery survive
  the restart, backed by the persistent `local-path` PVC described under Runtime expectations. Unlike
  the Grafana dashboard reprovisioning proof, this is not currently wired into a `just` recipe or test
  — treat it as a manual drill result, not a guarantee that holds for every future change.
- **DSPACE `ServiceMonitor` target health.** Operators have manually observed DSPACE's authenticated
  `ServiceMonitor` reporting two healthy Prometheus targets in staging. `scripts/observability_helm.sh`
  only asserts "at least one target, all healthy" (`verify_dspace_targets`), so the exact count of two
  is an observed fact at time of writing, not a value the verification script enforces.

## Follow-ups intentionally out of scope

Additional dashboards, Grafana persistence, central multi-cluster Grafana, and production
observability codification are separate follow-ups. The existing blackbox NetworkPolicy is unchanged.
Alerting onboarding — real Alertmanager receivers, external heartbeats, and failure drills — is no
longer undesigned scope creep; it is planned, designed work tracked in
[`docs/observability-alerting.md`](observability-alerting.md), just not yet executed.
