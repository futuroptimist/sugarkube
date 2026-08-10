# Observability operations runbook

This runbook covers the staging and production observability lifecycles. It is intentionally
non-Flux: operators use guarded Helm commands from this repository, with the chart version and
full values chain committed in Git. The production core stack has live acceptance evidence; the
application integrations listed below remain separately deferred.

## Canonical sources

- Chart version: `platform/observability/helm/kube-prometheus-stack.version` (`87.19.0`).
- Common values: `platform/observability/helm/kube-prometheus-stack.values.common.yaml`.
- Staging overrides: `clusters/staging/observability/kube-prometheus-stack.values.yaml`.
- Production overrides: `clusters/prod/observability/kube-prometheus-stack.values.yaml`.
- Canonical DSPACE rules: `platform/observability/rules/dspace-release-integrity.yaml`.
- Authoritative dashboard template:
  `platform/observability/dashboards/sugarkube-observability.template.json`.
- Deterministic generator: `scripts/generate_observability_dashboards.py`.
- Generated staging artifact:
  `clusters/staging/observability/dashboards/sugarkube-staging-observability.json`.
- Generated production artifact:
  `clusters/prod/observability/dashboards/sugarkube-prod-observability.json`.
- Helper: `scripts/observability_helm.sh` through `just observability-*` recipes.
- Alert delivery, routing, and drill strategy: [`docs/observability-alerting.md`](observability-alerting.md).
- DSPACE release-integrity triage and focused drills:
  [`docs/observability-dspace-release-integrity.md`](observability-dspace-release-integrity.md).
- Canonical staging node inventory: `clusters/staging/nodes.txt`.
- Host-heartbeat helper and assets: `scripts/observability_node_heartbeat.sh`,
  `scripts/sugarkube-node-heartbeat`, and `scripts/systemd/sugarkube-node-heartbeat.*`.

The dashboard is owned by Sugarkube and provisioned by the pinned Grafana
subchart. Every render, install, and upgrade passes the same standalone JSON
with Helm `--set-file`; the provider mounts it under
`/var/lib/grafana/dashboards/sugarkube`. The helper selects exactly one environment
dashboard: **Sugarkube Staging
Observability** (`sugarkube-staging-observability`) or **Sugarkube Production
Observability** (`sugarkube-prod-observability`). Grafana's chart-rendered
Prometheus datasource has stable UID `prometheus`, which both dashboards
reference directly.

Both environment artifacts intentionally share the same 11-row, 60-object panel layout. Regenerate
rather than hand-editing either artifact:

```bash
python3 scripts/generate_observability_dashboards.py --write
python3 scripts/generate_observability_dashboards.py --check
```

Their panel arrays are identical. Only the UID, title, environment tag, hidden `environment`
constant, and hidden `cluster` constant differ. The visible `app` and `route` selectors have the
same `All = .*` shape in both profiles. The validator compares each artifact to the authoritative
template and rejects one-sided title, query, visualization, transformation, target-mode, ID, order,
or grid drift.

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

## Production core-stack foundation

Read-only discovery on 2026-08-08 at merge SHA
`b650f760ffaeaa6f6d820bb2f4f99bf897b6854d` found context `sugar-prod`, identity
`env=prod` / `cluster=sugar`, and Ready nodes `sugarkube0`, `sugarkube1`, and
`sugarkube2`. Each node had four CPUs, about 8 GiB allocatable memory, and ample
local storage. The default `local-path` StorageClass used
`WaitForFirstConsumer`, did not allow expansion, and there were no PVs or PVCs.
The `monitoring` namespace, observability releases, and `monitoring.coreos.com`
APIs/CRDs were absent. No production application-metrics or blackbox lifecycle
was verified, and current application releases predate the staging metrics integrations.

The committed production baseline is one Prometheus replica with `7d` retention
and a `15GB` retention-size limit, backed by one `20Gi` ReadWriteOnce Prometheus
PVC using `local-path`. This storage is node-local and does not support
expansion, so capacity pressure or node loss requires explicit operator action.
The baseline also runs one Alertmanager replica using the null-only default
receiver. After one production week, operators should review observed retention,
WAL/PVC consumption, and memory before proposing capacity or retention changes.

Production live actions require an explicit kubeconfig and the `sugar-prod`
context; do not run the node-local staging kubeconfig recipe on `sugarkube3`:

```bash
export KUBECONFIG="$HOME/.kube/config-sugarkube-prod"
test "$(kubectl config current-context)" = sugar-prod
python3 scripts/cluster_identity.py assert --kubeconfig "$KUBECONFIG" --env prod
```

The checked-in production Grafana Secret declaration and the example age
recipient are scaffolding, not deployable live ciphertext. **Do not decrypt or
apply that file.** Also do not reconcile the full production overlay: it
contains observability resources whose CRDs do not exist until the core stack
is installed.

Generate and retain the production credentials in the operator's password
manager. Enter them only through the guarded hidden-TTY lifecycle; never paste
them into a command, environment variable, log, transcript, or file. With the
production context and identity checks above still in effect, install (or
intentionally rotate) and then check the Secret contract:

```bash
just observability-grafana-secret-install env=prod
just observability-grafana-secret-check env=prod
```

The install recipe creates only the `monitoring` Namespace, if absent, and
`monitoring/grafana-admin-credentials` with both required keys:

- Username key: `admin-user`.
- Password key: `admin-password`.

Both keys must be nonempty. The check recipe verifies only that key contract; it
does not return either value. The Helm install and upgrade preflight preserves
the same contract check.

## Production dashboard evidence and contract

The production core stack was successfully installed as Helm revision 1. Read-only evidence captured
on 2026-08-08 from repository SHA `2984f3fd5b39d391621f414ae01150cf6c0a7a59`
showed 23 of 23 active targets healthy in two distinct scrapes and three Ready nodes. The nine jobs
were `apiserver` (3), `coredns` (1), `kube-prometheus-stack-alertmanager` (2),
`kube-prometheus-stack-grafana` (1), `kube-prometheus-stack-operator` (1),
`kube-prometheus-stack-prometheus` (2), `kube-state-metrics` (1), `kubelet` (9), and
`node-exporter` (3). Sanitized candidate results showed three CPU values near 2.39–4.04%, three
memory values near 15.00–25.17%, three root-filesystem values near 6.26–6.50%, eleven zero
deployment deficits, six zero namespace problem-pod results, twenty zero restart-rate results, one
Prometheus-PVC value near 6.50%, and about 174,263 active series. No raw target, URL, instance,
address, error, or identity-label value was retained.

The production dashboard gives each signal the following operational meaning:

- **Scrape availability by job** takes the minimum `up` value per job, so any failed target makes
  that job unhealthy. **Ready nodes** deduplicates the Ready condition per node before summing;
  three is the observed visual expectation, not an alert threshold. **Node readiness** retains each
  node and distinguishes Ready (`1`), not Ready (`0`), and `NO DATA`.
- **Deployment replica deficit** independently takes the maximum desired and available gauges per
  namespace/deployment before subtracting and clamping negative values. **Unready pods by
  namespace** and **Problem pods by namespace** deduplicate pod (and bounded phase) gauges before
  summing. An emitted zero remains visible; an absent series stays `NO DATA`.
- **Container restart rate** deduplicates each namespace/pod/container counter, applies `rate` over
  Grafana's `$__rate_interval`, and then sums only containers belonging to the same namespace/pod.
  It does not impose a fixed production window.
- **Node CPU utilization**, **Node memory utilization**, and **Root filesystem utilization** join
  node-exporter samples to `node_uname_info` internally on `instance`, then group and display only
  `nodename`. The final output never exposes a scrape address or device. All three use a 0–100%
  scale, and CPU uses `$__rate_interval`.
- **Prometheus PVC utilization** takes bounded maxima for the available-byte numerator and
  capacity-byte denominator independently by namespace/PVC before division. **Prometheus active
  series** uses the maximum by pod and deliberately stays per pod; future replicas must not be
  summed into a misleading total.
- **Observability component build identity** uses one instant table union query over the four
  build-info metrics. Its fixed, bounded **Component** column contains only `prometheus`,
  `alertmanager`, `grafana`, or `node-exporter`, while the **Pod**, **Version**, and **Revision**
  columns preserve a row for each pod/version/revision identity without exposing raw instance or
  address labels or producing separate selectable query frames.
  `kube_state_metrics_build_info` was absent from the live inventory and is intentionally omitted,
  without a substitute signal.

All data panels explicitly render `NO DATA` for absence. Legitimate event-rate and health zeroes
are capability-gated; no query uses an unconditional `or vector(0)` substitution. The datasource
is single-cluster. Prometheus `externalLabels` are added
for remote/exported series, not to samples returned by local Prometheus queries, so dashboard
expressions must not select `cluster="sugarkube-prod"` (or any other external cluster label).

Grafana remains LAN-only at <http://sugarkube0.local:30300>, with the same NodePort on the other
production nodes and no public endpoint. Grafana persistence remains disabled: mutable UI-created
state is ephemeral, but the immutable dashboard is Helm-provisioned through its ConfigMap and
should reappear automatically after Grafana pod replacement. API verification remains the
acceptance proof after the replacement.

### Post-merge production procedure

1. Export `KUBECONFIG="$HOME/.kube/config-sugarkube-prod"`, verify the current context is
   `sugar-prod`, and run the production cluster-identity assertion shown above.
2. Keep the externally managed `127.0.0.1:16443` API tunnel running.
3. Run `just observability-render env=prod >/tmp/sugarkube-prod-render.yaml` and inspect it.
4. Run `just observability-upgrade env=prod`, **not install**, because Helm revision 1 exists.
5. Run `just observability-verify env=prod`.
6. Run `just observability-dashboard-verify env=prod`.
7. Delete only the Grafana pod, wait for the Grafana deployment rollout, and run dashboard
   verification again.
8. Visually inspect every panel at <http://sugarkube0.local:30300> with credentials retrieved from the operator vault.
9. Record the Git SHA, Helm revision, and private operator-evidence path.

Production application producers and integrations remain explicitly deferred. Until they are
separately deployed and verified, production intentionally shows `NO DATA` throughout **DSPACE
HTTP**, **DSPACE runtime and release**, **DSPACE feature traffic**, **Blackbox monitoring**,
**DSPACE release integrity**, **token.place relay and compute capacity**, and **token.place HTTP
and release**. Those panels are not placeholders and never convert absent telemetry into a healthy
zero. Event-rate zeroes require DSPACE instrumentation capability; image-pin, metrics-target, and
chat-synthetic fallbacks require `dspace_release_approved_info`. With the capability absent, the
query returns no series. The blackbox missing-data summary retains its seven-day discovery logic,
but no blackbox history still yields `NO DATA`.

Paging and alerts, persistent Grafana UI state, HA, and retention/storage changes also remain
deferred. This dashboard provisions none of those integrations. Merging this dashboard change does
not deploy either generated artifact: staging and production each require a separate guarded Helm
upgrade, visual acceptance, API verification, and retained evidence.

## Read-only preflight and status

```bash
just observability-render env=staging
just observability-status env=staging
just observability-verify env=staging
just observability-dashboard-verify env=staging
```

`env=int` is accepted only through the repository's deprecated alias normalization to
`staging`. Missing and unknown environments fail before Helm or kubectl activity;
`env=prod` and `env=production` select the guarded production core lifecycle.

Each helper prints the resolved environment, current Kubernetes context,
namespace, release, chart, pinned version, ordered values sources, and Grafana
LAN URL. Both environments report their selected dashboard source. Staging uses
the common
values, staging values, and a mode-`0600` temporary overlay generated from the
canonical DSPACE rules. Production uses common values followed by production
values and its production dashboard; it does not use the staging DSPACE rules
overlay. The helper reports stable canonical sources, never a random temporary
pathname.

## Render, install, and upgrade distinction

- `just observability-render env=staging` renders the complete pinned chart and values chain. It is read-only.
- `just observability-install env=staging` is for a fresh cluster. It renders first, checks the staging context, and fails if the Helm release already exists.
- `just observability-upgrade env=staging` is for steady-state changes. It renders first, checks the staging context, and fails if the Helm release does not exist.

The mutating recipes never use `--reuse-values`; the committed version, the two
committed values files, the generated canonical-rule overlay in that order, and
the dashboard source are always supplied. Before
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

1. Review changes to the version file, both committed values files, and the
   canonical DSPACE rule source.
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

### token.place Phase 1 dashboard slice

The two token.place rows use one environment-neutral layout. Their metric families have been
verified live in staging; production remains `NO DATA` until equivalent producers are verified.
They do not define alert thresholds:

- **token.place scrape availability** reports Prometheus `up` per relay pod,
  while **token.place instrumentation health** reports the application's own
  instrumentation self-check per relay pod. A value of one is healthy, zero is
  visibly unhealthy, and a missing series is `NO DATA`.
- **token.place compute-node counts** shows registered and healthy nodes.
  **token.place oldest compute-node lease age** shows the worst reported lease
  age, and **token.place compute-node eviction rate** splits the summed
  process-local counter rate by the bounded `reason` label.
- **token.place relay queue depth** and **token.place oldest queued-request
  age** split the logical queue gauges by bounded `provider_mode`.
  **token.place in-flight requests by pod** and **token.place oldest in-flight
  age by pod** deliberately retain relay-pod ownership: the application has not
  established that values from future relay replicas may safely be combined.
  **token.place terminal outcome rate** sums process-local counters and groups
  them by the bounded `outcome` label.
- **token.place HTTP request rate** groups summed counter rates by normalized
  `route` and bounded `status_class`. **token.place HTTP 5xx ratio** divides the
  summed 5xx rate by the summed request rate, and **token.place HTTP latency
  percentiles** derives p50, p95, and p99 from summed histogram-bucket rates by
  normalized route.
- **token.place build identity** is an instant table containing only `pod`,
  `version`, and `revision`.

Every token.place query selects the canonical `app=tokenplace`,
`release=tokenplace`, the hidden `$cluster`, and `namespace=tokenplace` labels plus the hidden
selected `$environment`. Logical gauges use `max` to deduplicate
values that future relay replicas may repeat instead of incorrectly adding
them. Process-local event counters use summed rates. No token.place state or
event query substitutes zero for an absent series: an emitted zero remains
zero, while absent instrumentation remains `NO DATA`. Queries and legends do
not expose raw targets, instances, node identities, request identifiers,
URLs, payloads, credentials, or other sensitive or unbounded labels.

A real encrypted staging request provided the Phase 1 functional evidence:
the single canonical Prometheus target was healthy; registered and healthy
nodes were both 1; in-flight requests moved `0 → 1 → 0`; the maximum observed
in-flight age was approximately 49.52 seconds; completed outcomes moved
`1 → 2`; queue depth and queued age stayed at 0; compute-node evictions stayed
at 0; and maximum lease age was approximately 28.15 seconds. The emitted
bounded outcomes were `completed`, `cancelled`, `expired`, `timed_out`,
`rate_limited`, `dependency_failure`, and `failed`. This is observed staging
evidence, not justification for alert thresholds.

The dashboard source and its fail-closed checks are deployed in staging. Helm revision 8 uses chart
`87.19.0`; that revision, its live ConfigMap, and repository `main` contain the same 44-panel
dashboard, whose canonical JSON SHA-256 is
`59cb188e015574a50a703c5000128d446896b1526f2d9fed9f7dde4ade32717b`. Functional chat
availability, schedulable-node capacity, availability-reason, and shared-state
health panels remain Phase 2 work and are not presented as implemented here.

- Helm release: `kube-prometheus-stack` in namespace `monitoring`.
- Prometheus: one replica, `7d` retention, `15GB` retention size, `local-path` `ReadWriteOnce` PVC requesting `20Gi`, CPU request `200m`, memory request `512Mi`, memory limit `2Gi`, admin API disabled, and external label `cluster=sugarkube-int`.
- Alertmanager: one replica with root/default no-op receiver named exactly
  `"null"`. The existing watchdog route, its order, and its 30-second group wait,
  one-minute group interval, and five-minute repeat interval remain preserved.
  The exact-label `SugarkubePagerDutyTest` route is deployed and has passed its
  manual fire/acknowledge/resolve delivery drill. The deployed staging allowlist also routes exactly
  `DspaceBuildRevisionMismatch`,
  `DspaceMixedBuildRevisions`, `DspaceDeploymentImagePinMismatch`,
  `DspaceChatSyntheticFailed`, and `DspaceMetricsTargetDown` to
  `pagerduty-dspace`. All five rules are loaded, healthy, and inactive in steady state. The
  owner-scoped #2329 drill proved live firing, acknowledgement, and resolution for the first,
  second, and fourth alerts; it did not deliberately fire all five.
  Its receiver uses the existing Secret-mounted PagerDuty integration and
  `send_resolved: true`; unrelated alerts continue to fall through to `"null"`.
  Deployment, collector/runner details, the sanitized verification record, and the reusable drill
  remain in the focused
  [DSPACE release-integrity runbook](observability-dspace-release-integrity.md).
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
# From a worktree checked out at the Git commit that produced <prior-revision>:
just observability-verify env=staging
# Run this only when that revision provisioned the dashboard.
just observability-dashboard-verify env=staging
```

The verification helper validates the configuration contract from its own Git
revision. Do not run the current helper against an older Helm revision: for
example, a revision from before PagerDuty support correctly lacks the current
Secret mount and synthetic route. If the matching repository revision is not
available, use `kubectl -n monitoring rollout status` for each workload shown by
`just observability-status env=staging`, inspect pod readiness and logs, and
check the Prometheus and Alertmanager endpoints without treating the current
configuration validator as rollback acceptance evidence. If `<prior-revision>`
predates the first dashboard-as-code rollout, a missing dashboard is likewise
the expected rollback state, so omit `observability-dashboard-verify`.

Do not use `--reuse-values` for the next forward upgrade; commit the full intended version and values chain first.

## PagerDuty staging fire and resolve runbook

Repository support alone is not deployment or delivery evidence. This manual procedure is staging-only; no CI,
render, install, upgrade, status, or verification command sends an alert.

This drill has been successfully completed end to end: phone receipt and acknowledgement were
confirmed, and resolution arrived after the expected default Alertmanager delay of approximately
five minutes. Retain the procedure below for regression drills.

1. Select and verify the staging context before creating or rotating anything:

   ```bash
   just kubeconfig-env env=staging
   test "$(kubectl config current-context)" = sugar-staging
   ```

2. Create or rotate the `monitoring/alertmanager-pagerduty` Secret without putting the routing key in
   history, arguments, files, or output. Run this from an interactive terminal (the hidden read is
   intentionally not suitable for a pasted automation transcript):

   ```bash
   read -r -s -p 'PagerDuty routing key: ' PAGERDUTY_ROUTING_KEY; printf '\n'
   printf %s "$PAGERDUTY_ROUTING_KEY" |
     kubectl -n monitoring create secret generic alertmanager-pagerduty \
       --from-file=routing-key=/dev/stdin --dry-run=client -o yaml |
     kubectl apply -f -
   unset PAGERDUTY_ROUTING_KEY
   ```

   The pipe keeps the value off the process list and disk. Neither command prints the Secret value.
3. Render and inspect the pinned proposal offline:

   ```bash
   just observability-render env=staging >/tmp/kube-prometheus-stack.rendered.yaml
   ruby scripts/verify_observability_alertmanager.rb rendered \
     /tmp/kube-prometheus-stack.rendered.yaml
   ```

   Confirm the validator reports the exact synthetic route, the exact five-alert
   DSPACE allowlist, file references, and Secret mount contract; remove the
   temporary render after review. This validates repository structure only; use
   the focused [DSPACE release-integrity runbook](observability-dspace-release-integrity.md)
   for the completed staging proof and repeatable regression drill.
4. Upgrade and verify:

   ```bash
   just observability-upgrade env=staging
   just observability-verify env=staging
   ```

   Upgrade fails closed before Helm mutation when the credential Secret or its nonempty key is absent.
5. Explicitly fire the bounded synthetic alert (it auto-ends after 15 minutes if abandoned):

   ```bash
   just observability-pagerduty-test env=staging action=fire
   ```

6. In PagerDuty, manually confirm phone receipt and acknowledge the incident. The repository cannot
   assert this external observation.
7. Resolve the same alert fingerprint, then manually confirm PagerDuty resolution:

   ```bash
   just observability-pagerduty-test env=staging action=resolve
   ```

8. If necessary, use `helm -n monitoring history kube-prometheus-stack`, roll back to the prior
   known-good revision with the command in [Rollback](#rollback), and run verification from the Git
   revision that produced that Helm revision (or use the configuration-neutral health checks described
   there).
9. Do **not** delete the credential Secret before rolling back configuration that references its
   mounted file. A missing mounted Secret can prevent Alertmanager from starting, including during a
   rollback whose configuration still expects it.
10. For rotation, repeat step 2 with the new value, then reload it deterministically and verify:

   ```bash
   kubectl -n monitoring rollout restart \
     statefulset/alertmanager-kube-prometheus-stack-alertmanager
   kubectl -n monitoring rollout status \
     statefulset/alertmanager-kube-prometheus-stack-alertmanager --timeout=20m
   just observability-verify env=staging
   ```

   Repeat the explicit fire/acknowledge/resolve confirmations. Revoke the old integration key only
   after the new path is proven. Keep the Secret present throughout rollback safety windows.

## Per-node Healthchecks.io heartbeat rollout

The heartbeat is platform/node observability and does not inspect Kubernetes, Helm, DSPACE, or any
other application. Debian Bookworm's systemd baseline supports `LoadCredential=`; the root-owned
mode-`0600` source credential is exposed only to the service's private runtime credential directory.
Installation refuses every environment except explicit `env=staging`, checks the local short
hostname against `clusters/staging/nodes.txt`, and reads only from the controlling terminal with echo
disabled. Do not pass a URL as an argument, environment variable, pipe, transcript, or command.

The heartbeat timers are installed on `sugarkube3`, `sugarkube4`, and `sugarkube5`. Use the following
procedure only for initial provisioning of another staging node, reprovisioning, or URL rotation.
Perform it on the affected physical node with its own rotated URL; `<ROTATED-NODE-PING-URL>` below is
a label, not text to paste.

1. Log in to the node, update `main`, and confirm that you are operating on the intended host:

   ```bash
   cd ~/sugarkube
   git switch main
   git pull --ff-only
   hostname -s
   ```

   Confirm that the output is the node currently being installed before continuing.
2. From an interactive terminal run `sudo just observability-node-heartbeat-install env=staging`.
   At the hidden prompt, paste that node's `<ROTATED-NODE-PING-URL>` and press Enter.
3. Run `sudo just observability-node-heartbeat-status env=staging`, then
   `sudo just observability-node-heartbeat-verify env=staging`. Verification explicitly starts one
   oneshot, waits for a successful result within its configured finite timeout, and leaves the
   recurring timer enabled.
4. In the **Sugarkube Staging** Healthchecks.io project, confirm only the corresponding node check
   changes from **New** to **Up**. Repeat on the next physical node with its distinct URL.

The timer runs 30 seconds after boot and every minute thereafter, with no more than five seconds of
randomized delay. Each check has two minutes of grace, so a sustained outage should page PagerDuty
after approximately one minute plus two minutes of grace.

For the safe first drill, identify a node that does **not** host Prometheus or Alertmanager, power it
down, confirm its Healthchecks.io check transitions late/down and the existing integration pages
PagerDuty, acknowledge the incident, restore power, then confirm the next heartbeat returns the check
to **Up** and the PagerDuty incident recovers/resolves. Do not start with the observability-hosting
node.

Rollback is destructive locally: run
`sudo just observability-node-heartbeat-uninstall env=staging`, then type `uninstall` at the terminal
confirmation. This disables the timer and removes only this feature's unit, executable, and local
credential. It does **not** delete or change Healthchecks.io checks, integrations, or PagerDuty
configuration. Deleting the credential means reinstall requires the node's rotated URL again.

The Alertmanager-driven observability watchdog configuration and operator workflows are
repository-ready, but await post-merge installation, deployment, and proof. In-cluster
`KubeNodeNotReady` routing and all application alert rules explicitly remain later tasks.

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
The synthetic Alertmanager → PagerDuty route is deployed and delivery-tested. External node-heartbeat
timers are installed on `sugarkube3`, `sugarkube4`, and `sugarkube5`; their node-power-off drill
remains outstanding. The watchdog's secret-safe configuration and operator workflows are
repository-ready, as tracked in [`docs/observability-alerting.md`](observability-alerting.md). Its
Secret installation, deployment, live confirmation, and failure-drill evidence remain post-merge
operator work.

## Observability watchdog

The staging-only `SugarkubeObservabilityWatchdog` rule is configured to evaluate `vector(1)` every
minute after deployment. Its exact
`staging`/`sugarkube-int`/`observability-watchdog` labels route only to the secret-file-backed
Healthchecks receiver. Alertmanager waits 30 seconds, groups by alert name, cluster, and environment,
and repeats every five minutes; configure the Healthchecks check for a **five-minute period and
two-minute grace**. Keep “last ping” confirmation manual: no Healthchecks account credential belongs
in this repository.

### Install, deploy, and verify

1. Select the `sugar-staging` context and run
   `just observability-watchdog-secret-install env=staging`. Input is hidden and must not be supplied
   in argv or environment variables. Check only its contract with
   `just observability-watchdog-secret-check env=staging`.
2. Run `just observability-render env=staging >/dev/null`, then
   `just observability-upgrade env=staging`. Install and upgrade refuse mutation unless both the
   PagerDuty `routing-key` and watchdog `ping-url` Secret contracts are nonempty.
3. Run `just observability-watchdog-verify env=staging`, then manually confirm Healthchecks **Last
   Ping** advances. The command checks the firing rule and exact labels, active Alertmanager alert,
   live CR/generated configuration, mount contract, and a bounded six-minute delivery-log window;
   it accesses neither credential.

Expected first delivery after deployment is within roughly 90 seconds (one-minute evaluation plus
30-second group wait), and repeats are five minutes apart. After a delivery stops, Healthchecks
should become late and page after its five-minute period plus two-minute grace. After the silence
expires or is cleared, recovery is expected on the next five-minute repeat; manually confirm both
the new Healthchecks ping and the PagerDuty incident's resolution. These are post-merge staging
checks, not deployment evidence from this change.

### Controlled failure drill and recovery

First manually confirm a recent successful Healthchecks ping. Run
`just observability-watchdog-drill-start env=staging`. It creates only an eight-minute Alertmanager
silence with the watchdog's exact four labels; automatic expiry preserves recovery if the operator
disconnects. The command sends JSON directly to Alertmanager through a temporary, automatically
allocated `127.0.0.1` port-forward and removes that listener when it finishes. It never shuts down a
node and never manually pings the URL. Inspect it with
`just observability-watchdog-drill-status env=staging`, or remove only that owned silence early with
`just observability-watchdog-drill-clear env=staging`. Automated tests inspect the payload and do not
wait eight minutes.

During the drill, manually confirm Healthchecks transitions to late/down, the Healthchecks-managed
PagerDuty integration creates an incident, and the incident can be acknowledged. After automatic
expiry (or early clear), confirm a new Alertmanager delivery returns Healthchecks to up and the
PagerDuty incident recovers and resolves. Re-run live verification.

> **ROLLBACK CHECKPOINT:** Before rolling back to any revision that removes the watchdog receiver,
> pause the Healthchecks check or its PagerDuty integration. Otherwise rollback itself generates a
> page. After pausing, perform the documented Helm rollback, verify the intended prior structure,
> and retain or remove the Kubernetes Secret only according to that revision's contract.

## Declarative application metrics verification

Sugarkube keeps application-specific Prometheus metrics contracts in the
strict JSON inventory at `platform/observability/app-metrics.json`. The live
verifier is generic: application names, metric families, bounded labels, Secret
names, ServiceMonitor names, retry bounds, and public `/metrics` status checks
come from that inventory.

For token.place staging, install or rotate the metrics bearer token before the
application deployment:

```bash
just observability-app-metrics-secret-install app=tokenplace env=staging
```

Validate that the configured Secret and key exist without decoding or printing
the value:

```bash
just observability-app-metrics-secret-check app=tokenplace env=staging
```

After staging deploys, verify the configured ServiceMonitor, Secret reference,
Prometheus target health, required metric families, bounded label enums, and the
expected unauthenticated public `401` response:

```bash
just observability-app-metrics-verify app=tokenplace env=staging
```

`just observability-verify env=staging` also runs every configured staging application
metrics verifier after the existing DSPACE checks. DSPACE production application `3.0.1` and chart
`3.0.2` use the production inventory contract with exactly two healthy targets and can be checked
with explicit production access:

```bash
export KUBECONFIG="$HOME/.kube/config-sugarkube-prod"
kubectl config use-context sugar-prod
just observability-app-metrics-secret-install app=dspace env=prod
just observability-app-metrics-secret-check app=dspace env=prod
just observability-app-metrics-verify app=dspace env=prod
```

Run those commands from `sugarkube3` through the externally managed `127.0.0.1:16443` tunnel; do not
use `just kubeconfig-env env=prod` there. Credential setup precedes the guarded values-only
reconciliation and does not promote the application or chart. Merging this repository support does
not deploy any application, create any
Secret, dashboard, alert rule, schedulability check, shared-state check, or live
drill.
