# token.place metrics-OOM and quota-exhaustion runbooks

These fail-closed operator runbooks implement the repository portion of
[Sugarkube #2779](https://github.com/futuroptimist/sugarkube/issues/2779) and are grounded in the
canonical postmortems for the
[2026-09-02 production relay metrics-cardinality OOM](https://github.com/futuroptimist/token.place/blob/main/outages/2026-09-02-production-relay-metrics-cardinality-oom.md)
and the
[2026-09-03 production public-information rate-limit exhaustion](https://github.com/futuroptimist/token.place/blob/main/outages/2026-09-03-production-public-information-rate-limit-exhaustion.md).
Implementation history is tracked in
[token.place PR #1763](https://github.com/futuroptimist/token.place/pull/1763). These runbooks do not claim
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

The helper preserves its Step 14a dry-run interface: it validates repository inventory and a
reviewed, privacy-safe JSON snapshot, then emits exact selections without invoking `kubectl`. The
snapshot must contain the exact Deployment, inventory-derived ServiceMonitor and four Probes. It
must also contain `OOMKilled`/137 termination evidence or bounded root/metadata 429 and healthy
livez/healthz statuses plus a successful quota-validator result. Use a unique DNS-safe run ID and
a new evidence file in an operator-supplied private directory outside the repository.
From the repository root, generate both plans (replace every placeholder with reviewed staging
coordinates):

```bash
python3 scripts/tokenplace_incident_drill.py --dry-run --mode metrics-oom \
  --host "$STAGING_HOST" --kubeconfig "$STAGING_KUBECONFIG" --context sugar-staging \
  --environment staging --namespace "$NAMESPACE" --deployment "$DEPLOYMENT" \
  --container "$CONTAINER" --current-image "$CURRENT_IMAGE_DIGEST" \
  --replacement-image "$REPLACEMENT_IMAGE_DIGEST" --rollback-image "$ROLLBACK_IMAGE_DIGEST" \
  --replicas "$REPLICAS" \
  --memory-limit "$MEMORY_LIMIT" --service-monitor "$SERVICE_MONITOR" \
  --run-id "$RUN_ID" --snapshot "$REVIEWED_PRIVATE_SNAPSHOT" \
  --evidence "$PRIVATE_EVIDENCE_DIRECTORY/${RUN_ID}-metrics-oom.json" \
  --acknowledge-state-loss
```

An offline plan is marked as a non-executing preview. The future live preflight calls
`scripts/cluster_identity.py assert --kubeconfig "$STAGING_KUBECONFIG" --env staging` first, then
reads only the exact Deployment, `ServiceMonitor/tokenplace`, and inventory-derived Probes through
that kubeconfig and context. It refuses drift before constructing any mutation. When the reviewed
current artifact exposes `TOKENPLACE_METRICS_MODE=normal|degraded`, containment uses the reversible
degraded value; otherwise it uses only the exact ServiceMonitor pause fallback. Replacement and
rollback remain bound to their separately reviewed immutable digests.

Repeat with `--mode quota-exhaustion`, a new run ID, and a new evidence filename. The generated
plan includes a deterministic digest. A future Step 14b operator can create its unique marker and
then execute or validate exactly one ordered stage per invocation (the live drill has **not** run):

```bash
python3 scripts/tokenplace_incident_drill.py --execute-stage marker \
  --plan "$PRIVATE_PLAN" --journal "$PRIVATE_JOURNAL_DIRECTORY" \
  --kubeconfig "$STAGING_KUBECONFIG"
python3 scripts/tokenplace_incident_drill.py --execute-stage "$NEXT_STAGE" \
  --plan "$PRIVATE_PLAN" --journal "$PRIVATE_JOURNAL_DIRECTORY" \
  --kubeconfig "$STAGING_KUBECONFIG" --gate-evidence "$PRIVATE_GATE_EVIDENCE"
```

Omit `--gate-evidence` for mutation stages. Gate evidence is a private JSON object keyed by the
plan's typed check names. Humans or external systems must supply real readiness, compute
registration and polling, encrypted request/response/retrieval/decryption, authenticated scrape,
quota-validation, and bounded observation results; the runner never fabricates them. Resume by
reissuing the same command: a journaled completed stage is a verified no-op, while a skipped stage,
changed plan, changed coordinates, or marker collision is refused. Apply only the exact inverse of
a completed mutation with:

```bash
python3 scripts/tokenplace_incident_drill.py --rollback-stage "$COMPLETED_MUTATION" \
  --plan "$PRIVATE_PLAN" --journal "$PRIVATE_JOURNAL_DIRECTORY" \
  --kubeconfig "$STAGING_KUBECONFIG"
```

After the original image and exact ServiceMonitor/Probe discovery labels are restored, and
`/livez` and `/healthz` are healthy, delete only the matching run-ID/digest marker. Repeating this
command reports the already-clean state without mutation:

```bash
python3 scripts/tokenplace_incident_drill.py --cleanup \
  --plan "$PRIVATE_PLAN" --journal "$PRIVATE_JOURNAL_DIRECTORY" \
  --kubeconfig "$STAGING_KUBECONFIG"
```

The operator must capture the schema-versioned JSON plan, precondition summary, authoritative
symptom, every printed mutation/rollback pair, Ready/digest/limit proof, compute registration and polling,
encrypted E2EE request/response/retrieval/decryption result, each bounded observation gate, quota
validator output, and final four-state change declaration. Evidence stays aggregate and redacted.

The runner creates one exact ConfigMap marker named from the unique run ID and plan digest and keeps
its append-only journal outside the repository. Cleanup never uses a selector, prefix, or broad
namespace deletion. A drill passes only when both incident classes demonstrate pause,
replacement, compute recovery, ordered restoration, threshold rollback, and exact cleanup while
health coverage remains uninterrupted. Update the canonical incident records and GitHub trackers
manually after review; use no automatic issue-closing action.
