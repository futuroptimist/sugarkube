# token.place metrics and quota incident response

This runbook is the repository implementation for
[Sugarkube issue 2779](https://github.com/futuroptimist/sugarkube/issues/2779) and the canonical
metrics-OOM and quota-exhaustion postmortems linked by
[token.place PR 1763](https://github.com/futuroptimist/token.place/pull/1763). It prepares the
Step 14b staging drill; it does **not** claim that drill has run.

## Safety contract

Classification is read-only. Mutation is a separate, explicitly authorized phase. The helper
requires a host, kubeconfig, context, environment, namespace, Deployment, container, current
immutable image digest, replacement and rollback digests, replica count, memory limit, exact
ServiceMonitor, and all four exact Probe names. Missing, duplicate, production, mutable, or
mismatched coordinates stop before mutation. It reads no Secret values or application logs and
does not print the host, kubeconfig, evidence path, credentials, source identities, request data,
ciphertext, prompts, responses, or private evidence locations.

Before every mutation the live path prints its exact inverse. `/livez` and `/healthz` are never
selected for mutation. A replacement loses process-local relay queues, registrations, leases,
in-memory rate counters, and other process state; authorization of that loss is mandatory. A
container restart preserves a Pod-lifetime `emptyDir`, including multiprocess metrics files. A Pod
replacement destroys that `emptyDir`; the helper deliberately replaces through the Deployment and
treats both relay-state and metrics-file loss as consequential.

Record four state assertions at classification and closure: **cluster changed**, **production
changed**, **repository changed**, and **external state changed**. A dry run sets all four false.
The drill may set only staging cluster state true. Repository review and later tracker updates are
external to the drill. Never close an incident or issue until evidence exists.

## Read-only classification

Capture only bounded, privacy-safe facts: Deployment generation, desired/available replica counts,
container name and digest, memory request/limit and utilization percentage, restart count,
`lastState.terminated` reason/exit code/time, event reasons and counts, exact Probe and
ServiceMonitor identity/labels, Prometheus target health and sample/cardinality totals, HTTP status
classes for the four declared public routes, and aggregate compute counts. Do not capture raw
paths, headers, identities, payloads, or Secret data.

An unready Pod is not OOM evidence. Classify metrics-OOM only when the application container has
authoritative `lastState.terminated.reason=OOMKilled` **and** exit code `137`. For quota exhaustion,
distinguish a total outage (failed `/livez` or `/healthz`) from route-specific `429` responses while
both health routes remain successful. Inspect only the names/presence of effective limiter hourly
and daily quotas, exact method/path exemptions, proxy-aware identity mode, and backing-store mode.
Run `python scripts/validate_probe_quotas.py --environment staging`; its declarative contract at
`config/observability/probe-quotas.yaml` is authoritative for exact method/path semantics, shared
buckets, scrape fanout, multipliers, and safety margin.

## Containment and recovery

### Metrics OOM

Pause only `ServiceMonitor/monitoring/tokenplace` by removing its discovery `release` label. This
does not alter root, metadata, livez, or healthz Probes. If the exact deployed artifact exposes the
reviewed emergency degraded-metrics setting, feature-detect it from the Deployment schema and use
it only with its documented value and inverse. Older rollback artifacts may lack it; exact-target
ServiceMonitor pause remains the supported fallback.

Keep scraping paused until authentication still returns the expected public `401`, required metric
families and bounded labels pass the application-metrics verifier, cardinality and scrape cost stay
within reviewed inventory bounds, memory is at most 80% of its limit, and there are zero new
restarts/OOMs during a 15-minute window. Compute and encrypted functional gates below must also pass.
Restore metrics last by restoring the exact `release=kube-prometheus-stack` label; its inverse is
removing that label again.

### Quota exhaustion

Pause exactly the token.place root and metadata Probe objects, retaining livez and healthz. Confirm
their exact GET `/` and GET `/api/v1/meta` declarations in the quota contract; do not use prefix or
route-class guesses. Replacement when counters are in memory resets enforcement state and needs
explicit incident-command authorization—it is not an informal quota reset. Re-run the quota
validator before restoration. Restore root first, observe, then metadata, and observe again. Each
rollback removes the discovery label only from the route just restored.

## Mandatory sequence and gates

The sequence is fixed: **pause affected discovery → deploy/replace → readiness and exact artifact
identity → compute registration and polling → encrypted request/response/retrieval/decryption →
root → observe → metadata → observe → application metrics last → extended observe**. Skip a restore
step only when that incident class never paused it. Every replacement requires a real compute node
to re-register, renew/poll successfully, and complete a relay-blind encrypted E2EE transaction whose
request, response, retrieval, and client-side decryption are verified without retaining payloads.

| Gate | Window | Roll back immediately when |
| --- | --- | --- |
| workload | 180 seconds | desired readiness or exact digest is absent; any new restart/OOM |
| root | 300 seconds | any health failure, 429, 5xx, restart, or memory above 80% |
| metadata | 300 seconds | any health failure, 429, 5xx, or quota validator failure |
| metrics | 900 seconds | scrape `up != 1`, authentication failure, unreviewed series/label, excess scrape cost/cardinality, memory above 80%, restart, or OOM |

At a gate failure, apply the rollback printed for the most recently restored exact resource; if the
replacement itself fails, set the container to the supplied immutable rollback digest. Do not
disable livez or healthz. After the extended gate, update both canonical incident records and the
GitHub trackers with the privacy-safe summary and reviewer links. Tracker closure remains manual.

## Step 14b non-production drill

Create a unique operator-owned directory with mode `0700`; never put it in the repository. Export a
bounded snapshot matching the schema exercised in `tests/test_tokenplace_incident_drill.py`. Use a
unique drill identifier in evidence metadata and any temporary staging-only compute registration;
do not put it in resource names managed by this helper. First prove selection without a cluster:

```bash
python scripts/tokenplace_incident_drill.py \
  --incident metrics-oom --host "$STAGING_HOST" --kubeconfig "$STAGING_KUBECONFIG" \
  --context sugar-staging --environment staging --namespace tokenplace \
  --deployment tokenplace --container relay --image "$CURRENT_IMAGE_DIGEST" \
  --replacement-image "$RECOVERY_IMAGE_DIGEST" --rollback-image "$CURRENT_IMAGE_DIGEST" \
  --replicas "$EXPECTED_REPLICAS" --memory-limit "$EXPECTED_MEMORY_LIMIT" \
  --monitor-namespace monitoring --service-monitor tokenplace \
  --root-probe blackbox-tokenplace-staging-root \
  --metadata-probe blackbox-tokenplace-staging-metadata \
  --livez-probe blackbox-tokenplace-staging-livez \
  --healthz-probe blackbox-tokenplace-staging-healthz \
  --snapshot "$BOUNDED_SNAPSHOT" --evidence-dir "$PRIVATE_EVIDENCE_DIR"
```

Repeat with `--incident quota-exhaustion`. For the future live run, omit `--snapshot`, add
`--execute --authorize-state-loss --confirm-encrypted-e2e`, and add one `--completed-gate NAME` for
each gate only after its evidence is reviewed. The procedure is safely resumable: label patches and
setting an already-selected image are idempotent, and an omitted gate stops progress. Exact cleanup
restores root, then metadata, then ServiceMonitor labels when they were paused; sets the approved
rollback image if recovery failed; deletes only the uniquely identified temporary compute/drill
resources; and retains the private summary according to incident policy.

Acceptance evidence is `summary.json` schema version 1 plus timestamps and reviewer attestations for
preconditions, authoritative OOM or bounded 429 classification, every printed rollback, readiness
and digest, compute registration/polling, encrypted E2EE, both five-minute route windows, the
15-minute metrics window, quota-validator output, exact cleanup, and all four final state assertions.
The summary contains aggregates and resource kinds/names only—never credentials, identities, raw
requests, ciphertext, or private paths. Run both incident classes. A dry run is not Step 14b.
