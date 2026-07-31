# Observability operations runbook

This runbook covers the current live **staging-only** kube-prometheus-stack lifecycle. It is intentionally non-Flux: operators use guarded Helm commands from this repository, with the chart version and full values chain committed in Git.

Production observability is intentionally unsupported in this slice because no production live baseline has been proven yet.

## Canonical sources

- Chart version: `platform/observability/helm/kube-prometheus-stack.version` (`87.19.0`).
- Common values: `platform/observability/helm/kube-prometheus-stack.values.common.yaml`.
- Staging overrides: `clusters/staging/observability/kube-prometheus-stack.values.yaml`.
- Staging dashboard: `clusters/staging/observability/dashboards/sugarkube-staging-observability.json`.
- Helper: `scripts/observability_helm.sh` through `just observability-*` recipes.
- Alert delivery, routing, and drill strategy: [`docs/observability-alerting.md`](observability-alerting.md).
- Canonical staging node inventory: `clusters/staging/nodes.txt`.
- Host-heartbeat helper and assets: `scripts/observability_node_heartbeat.sh`,
  `scripts/sugarkube-node-heartbeat`, and `scripts/systemd/sugarkube-node-heartbeat.*`.

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
- Alertmanager: one replica with root/default no-op receiver named exactly `"null"`. Staging values
  define a secret-file-backed PagerDuty receiver, but route only the exact synthetic test labels to
  it; bundled and real workload alerts still fall through to `"null"`. Repository configuration is
  is deployed, and its manual fire/acknowledge/resolve drill has been proven. Bundled and real
  workload alerts still fall through to `"null"`.
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

   Confirm the validator reports the exact synthetic route, file reference, and Secret mount contract;
   remove the temporary render after review.
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

After this change merges, perform these steps **separately on each of `sugarkube3`, `sugarkube4`, and
`sugarkube5`**. Use that physical node's own rotated URL; `<ROTATED-NODE-PING-URL>` below is a label,
not text to paste.

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

The Alertmanager-driven observability watchdog, in-cluster `KubeNodeNotReady` routing, and all
application alert rules explicitly remain later tasks.

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
assets and the watchdog's secret-safe configuration and operator workflows are repository-ready, as
tracked in [`docs/observability-alerting.md`](observability-alerting.md). Their installation,
deployment, live confirmation, and failure-drill evidence remain post-merge operator work.

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
disconnects. It never shuts down a node and never manually pings the URL. Inspect it with
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
