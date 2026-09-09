# token.place metrics-OOM and quota-exhaustion response

This runbook implements the repository half of [Sugarkube issue #2779](https://github.com/futuroptimist/sugarkube/issues/2779). The canonical metrics-OOM and quota-exhaustion postmortems are the incident records linked by [token.place PR #1763](https://github.com/futuroptimist/token.place/pull/1763). Those records and their trackers remain authoritative. **No live drill is claimed here**: the staging exercise is the separate Step 14b.

## Safety contract

Classification is read-only. Before mutation, record an operator-reviewed, privacy-safe snapshot containing exactly one deployment, container, ServiceMonitor, and each of the root, metadata, `/livez`, and `/healthz` Probes. Match the explicit host, kubeconfig, context, environment, namespace, deployment, container, current immutable image digest, desired immutable image digest, rollback digest, replica count, and container memory limit. Missing, duplicate, mutable, or contradictory coordinates stop the procedure. The drill helper accepts only staging and rejects a production context or production host.

Never put Secrets, authentication headers, public keys, source identities, request identifiers, ciphertext, prompts, responses, raw/unbounded paths, or a private evidence location in snapshots, transcripts, incidents, or trackers. Record only counts, booleans, bounded route/status classes, resource names, immutable artifact identities, timestamps, and aggregates. Capture:

* Deployment desired/ready counts, exact digest and memory limit; bounded restart count and termination reason.
* Bounded event-reason/count summaries (not messages), exact Probe and ServiceMonitor names/labels, endpoint status classes, and `root`, `metadata`, `livez`, and `healthz` route classes.
* Aggregate 429/5xx rates, scrape health, bounded series/sample counts, scrape duration, working-set/limit ratio, and compute/E2EE pass booleans.
* Whether cluster, production, repository, and external state changed. A dry-run sets all false. A staging execution sets only `cluster_changed`; it must not mutate production, GitHub, Helm release state, or external services.

The helper prints an exact rollback command **before** each command. Stop on the first failure and run that rollback. Never use a transient Pod name, UID, Helm revision, or old tag as a coordinate.

## Read-only classification

Use explicitly scoped `kubectl --kubeconfig ... --context ... get` and JSONPath or `jq` projections that omit Secret/env values, target URLs, event messages, and payloads. Do not use `kubectl describe`, dump a Secret, or capture unrestricted logs. Confirm `/livez` and `/healthz` independently; their success distinguishes route-specific degradation from total outage.

### Metrics OOM

An unready Pod is not OOM evidence. Require the selected application container's `lastState.terminated.reason=OOMKilled` **and** exit code `137`. Capture bounded memory, restart, scrape health, series/sample count, and scrape-duration aggregates. Confirm the selected ServiceMonitor is the one exact application-metrics discovery target.

Pause discovery by removing only that ServiceMonitor's `release=kube-prometheus-stack` label. This edits no Probe; root, metadata, `/livez`, and `/healthz` remain active. If the deployed immutable artifact's documented schema proves it supports emergency `TOKENPLACE_METRICS_MODE=degraded`, the plan may enable it. Otherwise retain the exact-ServiceMonitor pause fallback. Never guess that an older rollback artifact supports degraded mode.

A container-process restart and Pod replacement differ. A process restart loses process-local relay state but retains files in the Pod-lifetime metrics `emptyDir`; replacing the Pod loses both process-local state **and** its multiprocess metric files. Neither clears state without explicit authorization. Replacement always requires compute re-registration, polling, and encrypted request/response/retrieval/decryption verification. Keep metrics paused until bounded cardinality, authenticated scrape, memory, restart, compute, and functional gates pass.

### Quota exhaustion

Determine whether the app is unavailable or only exact route/method pairs return 429 while `/livez` and `/healthz` succeed. Inspect only safe metadata: effective hourly/daily limits, exact exempt route/method pairs, identity strategy name, and storage backend type. Never print identity values, credentials, headers, or stored keys.

Run the declarative contract before pausing anything:

```bash
python3 scripts/validate_probe_quotas.py --environment staging
```

Use its exact route/method, shared bucket, scrape fanout, multiplier, safety margin, and unlimited-operational declarations to identify consumers. Pause only root and metadata Probes by removing their discovery label. `/livez` and `/healthz` remain selected. Replacement resets in-memory limiter counters and process-local relay state; treat this as authorized state loss, not remediation, and require all compute and encrypted E2EE recovery checks.

## Ordered recovery and bounded gates

The immutable order is:

1. Pause only incident-specific discovery targets, then deploy/replace.
2. Within 5 minutes, require desired replicas ready at the exact digest, no new restart/OOM, and memory below 80%.
3. Re-register compute, prove polling, then prove encrypted end-to-end request, response, retrieval, and client-side decryption. Relay plaintext is never evidence.
4. Restore root; observe 10 minutes.
5. Restore metadata; validate the quota schedule and observe 10 minutes.
6. Restore application metrics last by the exact inverse ServiceMonitor operation; observe 30 minutes.

For metrics-OOM, root and metadata were never paused, so steps 4–5 are already satisfied, but their gates apply. During every window, rollback on readiness loss lasting 2 minutes, any restart/OOM, memory at or above 90% for 2 minutes, any health-probe failure, any 5xx in two consecutive probe intervals, more than one route-specific 429 in two intervals, scrape down for two intervals, unauthenticated scrape success, a greater than 10% increase over the reviewed bounded series/sample budget, or scrape duration above 80% of timeout twice. Root/metadata failures remove only that Probe label. Metrics failure removes only the ServiceMonitor label. Artifact/readiness/compute/E2EE failure restores the printed rollback digest and repeats compute recovery.

After interruption, do not shorten a window: record the completed phase and restart its whole window. Finish by updating both canonical records and GitHub trackers with reviewed evidence; do not automate or claim closure before evidence exists.

## Step 14b staging drill (future work)

Create a unique `mktemp -d` directory, mode `0700`, outside the repository. Write `snapshot.json` from reviewed read-only output. Its name is not evidence and must not be printed or committed. Dry-run is idempotent. After interrupted execution, inspect exact labels/digest, retain completed phase names in the aggregate summary, and resume only at the first incomplete phase; never blindly rerun mutation.

```json
{
  "matches": {"host": "STAGING_HOST", "context": "STAGING_CONTEXT", "environment": "staging", "namespace": "NAMESPACE", "deployment": "DEPLOYMENT", "container": "CONTAINER", "image": "REPOSITORY@sha256:ROLLBACK_DIGEST", "replicas": 1, "memory_limit": "REVIEWED_LIMIT", "service_monitor": "SERVICE_MONITOR", "probes": ["ROOT_PROBE", "METADATA_PROBE", "LIVEZ_PROBE", "HEALTHZ_PROBE"]},
  "target_counts": {"deployment": 1, "container": 1, "service_monitor": 1, "root_probe": 1, "metadata_probe": 1, "livez_probe": 1, "healthz_probe": 1},
  "health_probe_labels": {"LIVEZ_PROBE": true, "HEALTHZ_PROBE": true},
  "oom": {"reason": "OOMKilled", "exit_code": 137},
  "quota_contract_valid": true, "degraded_metrics_supported": false
}
```

Run this exact command first **without** `--execute`; repeat with `--incident quota-exhaustion`. It validates selection and emits a safe summary without cluster access. Resolve variables from current staging classification, not this document.

```bash
python3 scripts/tokenplace_incident_drill.py \
  --incident metrics-oom --host "$STAGING_HOST" \
  --kubeconfig "$KUBECONFIG" --context "$STAGING_CONTEXT" \
  --environment staging --namespace "$NAMESPACE" \
  --deployment "$DEPLOYMENT" --container "$CONTAINER" \
  --image "$IMAGE_REPOSITORY@$DESIRED_DIGEST" \
  --rollback-image "$IMAGE_REPOSITORY@$ROLLBACK_DIGEST" \
  --replicas "$REPLICAS" --memory-limit "$MEMORY_LIMIT" \
  --service-monitor "$SERVICE_MONITOR" --root-probe "$ROOT_PROBE" \
  --metadata-probe "$METADATA_PROBE" --livez-probe "$LIVEZ_PROBE" \
  --healthz-probe "$HEALTHZ_PROBE" --snapshot "$DRILL_DIR/snapshot.json" \
  --evidence-summary "$DRILL_DIR/summary.json"
```

Only in the future authorized drill, append `--execute` and all five confirmation flags from `--help`. They attest separately to state-loss authorization, compute registration, polling, encrypted E2EE, and reviewed gates. Acceptance evidence is the aggregate summary; timestamps and pass/fail for every gate/window; exact names/digests; rollback commands/results; and all four state-change declarations, for both incidents. It must contain no target URL or private path.

Cleanup is exact: ensure all four Probes and the ServiceMonitor have `release=kube-prometheus-stack`; restore the reviewed desired digest (or printed rollback digest after failure); remove the feature-detected degraded-mode override if added; then delete only the unique directory. Re-run the quota validator and all gates after cleanup. Preserve an approved redacted aggregate summary elsewhere before deletion; never retain the private working path.
