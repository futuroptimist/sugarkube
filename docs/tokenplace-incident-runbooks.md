# token.place metrics-OOM and quota-exhaustion runbooks

These fail-closed operator runbooks implement the repository portion of
[Sugarkube #2779](https://github.com/futuroptimist/sugarkube/issues/2779) and are grounded in the
canonical incident records linked by
[token.place PR #1763](https://github.com/futuroptimist/token.place/pull/1763). They do not claim
that the Step 14b staging drill has run. Never use this procedure to close an incident or tracker
before the evidence and human review exist.

## Safety contract shared by both incidents

Classification is read-only. Mutation is a separately authorized phase. Before mutation, record
explicit values for the public host, kubeconfig, context, environment, namespace, Deployment,
container, immutable `image@sha256:...`, desired replica count, container memory limit, exact
ServiceMonitor, and the four exact token.place Probe names. Stop on a missing, duplicate, or
mismatched object, selector, container, image, replica count, limit, host, or cluster identity.
Production requires a distinct approval and is deliberately rejected by the drill helper.

Capture a privacy-safe summary of Deployment generation/readiness, container termination reason
and exit code, aggregate warning-event reasons/counts, Probe and ServiceMonitor names/selectors,
endpoint status classes, public route classes, restart deltas, aggregate scrape health/series cost,
and memory working-set percentage. Do **not** retain targets, credentials, authentication headers,
source identities, raw/unbounded paths, request IDs, ciphertext, prompts, responses, keys, or
private evidence paths. Inspect limiter values and Secret *references/key presence*, never Secret
values. Every report must state independently whether cluster, production, repository, and external
state changed.

Before every mutation, print its exact kind/namespace/name, old immutable image or discovery label,
replacement value, and inverse command. The helper's plan contains a `rollback` beside every
mutation. Do not proceed when a rollback coordinate is a placeholder: resolve the exact previous
digest first. A replacement destroys process-local registrations, leases, queues, and in-memory
limiter counters. This state loss requires explicit authorization even when it appears helpful.

After any replacement, the mandatory order is:

1. Deployment replacement; then Ready replicas equal desired replicas within 5 minutes and every
   container reports the approved digest and memory limit.
2. Re-register a real compute node, observe registration, and prove polling resumes.
3. Complete an encrypted request, compute response, retrieval, and client-side decryption. Health,
   diagnostics, or synthetic registration alone cannot substitute for this relay-blind E2EE proof.
4. Restore the root Probe; observe for 15 minutes.
5. Restore the metadata Probe; observe for 15 minutes.
6. Restore application metrics **last**; observe for 30 minutes.

`/livez` and `/healthz` stay discovered throughout. At every gate, immediately apply the rollback
printed for the current restoration if readiness drops, desired readiness is not reached in 5
minutes, restarts increase, any new `OOMKilled`/137 termination occurs, route-specific 429s exceed
1% over 5 minutes, 5xx responses exceed 1% over 5 minutes, scrape health is not 100%, active-series
cardinality or scrape samples exceed the reviewed baseline by 10%, or memory working set reaches
85% of the limit for 5 minutes. Roll back the replacement digest if workload, compute, or E2EE
checks fail. These are ceilings; a stricter incident-specific threshold wins.

## Metrics OOM

### Read-only classification

Unready is not OOM evidence. Require the affected container's
`lastState.terminated.reason=OOMKilled` **and** exit code `137`, correlate its timestamp with a
restart increment and memory observations, and reject ambiguous multi-container/multi-pod results.
Confirm `/livez` and `/healthz` separately. Capture only aggregate/cardinality-safe metrics metadata.

Check whether the exact deployed digest exposes the supported emergency degraded-metrics setting
in its rendered Deployment/chart contract. If present, use that reviewed setting and record its
inverse. Never assume a rollback artifact implements it. When absent, remove only the exact affected
ServiceMonitor's `release: kube-prometheus-stack` discovery label, retaining its identifying pause
label and inverse operation. Do not modify any Probe: root, metadata, `/livez`, and `/healthz` remain.

### Replacement semantics and exit

A container restart preserves its Pod and therefore preserves files in the pod-lifetime `emptyDir`;
stale multiprocess metric shards can remain. Pod replacement deletes that `emptyDir` and creates a
clean one, but also loses all process-local relay state. Select deliberately and record which
lifecycle occurred. Scraping stays paused until the deployed build's bounded-cardinality behavior,
authenticated scrape, memory below 70% for 15 minutes, zero restart/OOM delta, compute registration
and polling, and encrypted E2EE flow all pass. Restore metrics last by restoring only the exact
ServiceMonitor discovery label. Its inverse removes that label again.

## Quota exhaustion

### Read-only classification

First distinguish a total outage from route-specific HTTP 429 responses: confirm `/livez` and
`/healthz` remain 2xx and classify root and `/api/v1/meta` independently. Inspect the effective
hourly/daily limits, exact method/path exemptions, trusted-proxy identity policy, and in-memory or
shared storage mode without printing values that identify callers or expose Secrets.

Run the declarative contract before mitigation:

```bash
python3 scripts/validate_probe_quotas.py --env staging
```

The contract identifies exact `GET /` and `GET /api/v1/meta` consumers, shared buckets, scrape
fanout, multipliers, margins, and exemptions. Pause only
`blackbox-tokenplace-staging-root` and `blackbox-tokenplace-staging-metadata` by removing their
discovery labels. Never pause the health Probes. A process replacement with in-memory counters is
state loss, not a quota reset procedure; require authorization and all compute/E2EE recovery gates.

Before restoration, rerun the quota validator. Restore root, verify the 15-minute gate and quota
headroom, then restore metadata and repeat. Metrics restoration remains last. If a restored route
crosses a rollback threshold, remove only that Probe's discovery label using the printed inverse.

## Step 14b: prepared staging drill (not yet performed)

The helper is intentionally dry-run-only in Step 14a: it validates repository inventory and emits
exact selections without invoking `kubectl`. Use a unique DNS-safe run ID and a new evidence file.
From the repository root, generate both plans (replace every placeholder with reviewed staging
coordinates):

```bash
python3 scripts/tokenplace_incident_drill.py --dry-run --mode metrics-oom \
  --host "$STAGING_HOST" --kubeconfig "$STAGING_KUBECONFIG" --context sugar-staging \
  --environment staging --namespace "$NAMESPACE" --deployment "$DEPLOYMENT" \
  --container "$CONTAINER" --image "$IMAGE_DIGEST" --previous-image "$PREVIOUS_IMAGE_DIGEST" \
  --replicas "$REPLICAS" \
  --memory-limit "$MEMORY_LIMIT" --service-monitor "$SERVICE_MONITOR" \
  --run-id "$RUN_ID" --evidence "evidence/${RUN_ID}-metrics-oom.json" \
  --acknowledge-state-loss
```

Repeat with `--mode quota-exhaustion`, a new run ID, and a new evidence filename. Step 14b must add
a separately reviewed execution adapter; the Step 14a helper cannot mutate a cluster. The operator
must capture the schema-versioned JSON plan, precondition summary, authoritative injected symptom,
every printed mutation/rollback pair, Ready/digest/limit proof, compute registration and polling,
encrypted E2EE request/response/retrieval/decryption result, each bounded observation gate, quota
validator output, and final four-state change declaration. Evidence stays aggregate and redacted.

Create temporary drill resources with the unique run ID, resume only when their recorded phase and
coordinates match, and reject an existing evidence file. Cleanup deletes only resources bearing
that exact run ID after restoring the original digest and discovery labels; rerunning cleanup must
report an already-clean state. A drill passes only when both incident classes demonstrate pause,
replacement, compute recovery, ordered restoration, threshold rollback, and exact cleanup while
health coverage remains uninterrupted. Update the canonical incident records and GitHub trackers
manually after review; use no automatic issue-closing action.
