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

The helper preserves its Step 14a real-incident dry-run interface: it validates repository inventory and a
reviewed, privacy-safe JSON snapshot, then emits exact selections without invoking `kubectl`. The
snapshot must contain the exact Deployment, inventory-derived ServiceMonitor and four Probes. It
must also contain `OOMKilled`/137 termination evidence or bounded root/metadata 429 and healthy
livez/healthz statuses plus a successful quota-validator result. Use a unique DNS-safe run ID and
a new evidence file in an operator-supplied private directory outside the repository.
From the repository root, generate both plans (replace every placeholder with reviewed staging
coordinates):

The runner and its live quota preflight use only Python's standard library. The runner's small,
strict JSON projection of the token.place Probe coordinates is committed at
`config/observability/tokenplace-incident-probes.json` and is checked against the full quota
contract in tests. The quota validator uses a strict reader limited to the repository's reviewed
YAML forms and still validates the complete contract and rendered Probe graph. No Python package
installation or repository bootstrap is required before using the commands below on an operator
host.

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

For a controlled metrics-OOM rehearsal starting from a healthy baseline, select the separate
lifecycle and provide a fourth immutable identity. `CURRENT_IMAGE_DIGEST` is the healthy baseline,
`INCIDENT_IMAGE_DIGEST` is the reviewed fault stimulus, `REPLACEMENT_IMAGE_DIGEST` is the recovery
candidate, and `ROLLBACK_IMAGE_DIGEST` is the reviewed emergency fallback. All four must be
distinct. The second acknowledgement authorizes staging-only fault injection; the existing
acknowledgement separately recognizes replacement of process-local and `emptyDir` state:

```bash
python3 scripts/tokenplace_incident_drill.py --dry-run --mode metrics-oom \
  --lifecycle staging-rehearsal --incident-image "$INCIDENT_IMAGE_DIGEST" \
  --host "$STAGING_HOST" --kubeconfig "$STAGING_KUBECONFIG" --context sugar-staging \
  --environment staging --namespace "$NAMESPACE" --deployment "$DEPLOYMENT" \
  --container "$CONTAINER" --current-image "$CURRENT_IMAGE_DIGEST" \
  --replacement-image "$REPLACEMENT_IMAGE_DIGEST" --rollback-image "$ROLLBACK_IMAGE_DIGEST" \
  --replicas "$REPLICAS" --memory-limit "$MEMORY_LIMIT" \
  --service-monitor "$SERVICE_MONITOR" --run-id "$RUN_ID" \
  --snapshot "$HEALTHY_PRIVATE_SNAPSHOT" \
  --evidence "$PRIVATE_EVIDENCE_DIRECTORY/${RUN_ID}-metrics-oom-rehearsal.json" \
  --acknowledge-state-loss --acknowledge-staging-fault-injection
```

The rehearsal snapshot must describe the healthy baseline and have an empty `classification`;
fixture OOM fields are refused in this lifecycle. Offline output labels fixture classification as
non-authoritative and declares zero cluster, production, repository, and external state changes.
It is a plan preview, not proof that an OOM occurred and not authorization to execute.

After independent review of that preview, generate the executable plan by repeating the same
command with a new evidence filename and replacing
`--snapshot "$HEALTHY_PRIVATE_SNAPSHOT"` with `--live-preflight`. This read-only authoritative
preflight asserts staging identity first, reads the exact Deployment, ServiceMonitor, and four
Probes, requires desired and available replicas to equal the reviewed replica count, and confirms
the healthy image, memory limit, metrics mode, and unpaused discovery labels. It does not look for
an OOM before building the rehearsal plan. An offline rehearsal plan is cryptographically distinct
and the execution interface refuses it.

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

For the rehearsal, the exact order begins with `marker`, `inject-incident-image`,
`generate-bounded-cardinality`, and `observe-authentic-oom`, followed by the existing containment,
recovery replacement, readiness,
compute registration and polling, relay-blind encrypted E2EE, route preservation, metrics-exit,
metrics-last restoration, and final observation stages. Changing the image alone cannot advance
to authentic observation. Image injection authorization does not authorize traffic. Execute the
traffic stage separately, after reviewing its plan coordinates, with its dedicated acknowledgement:

```bash
python3 scripts/tokenplace_incident_drill.py \
  --execute-stage generate-bounded-cardinality \
  --acknowledge-bounded-cardinality-generation \
  --plan "$PRIVATE_PLAN" --journal "$PRIVATE_JOURNAL_DIRECTORY" \
  --kubeconfig "$STAGING_KUBECONFIG"
```

The trigger is fixed at 72,000 synthetic unique unmatched paths and 72,000 total requests, with
concurrency 16, a ceiling of 400 requests per second, a 240-second wall-clock limit, and a
five-second per-request timeout. It uses only HTTPS to `staging.token.place`, requires every
response to remain on the exact requested staging URL without redirects and to be 404, and stops
at the first failure, timeout, interruption, or bound. Paths are deterministically derived from
the run ID and sequence; no credentials, payloads, user input, or production host can enter them.
Only counts, status aggregates, and a SHA-256 path-set commitment enter the private journal—never
the raw paths. The plan prints the forward action, cancellation boundary, healthy-image recovery,
and exact marker cleanup coordinates.

Worker cancellation is joined before recovery begins. A failure or interruption records a
privacy-safe stopped summary, restores the exact healthy image, reasserts the reviewed staging
identity and Deployment coordinates, verifies `/livez` and `/healthz`, and deletes only the exact
run-owned marker. The append-only private journal remains in place. Never resume an interrupted
traffic stage or either prior failed live run ID; create a newly reviewed plan and run ID.

Do not supply `--gate-evidence` to
`observe-authentic-oom`: that gate reads the current Deployment, its unambiguous owned ReplicaSet
and Pod, the exact container/image/memory limit, its OOMKilled/137 last termination, positive
restart count and timestamp, and privacy-safe event aggregates directly through the bound staging
kubeconfig. Its lower time boundary is the durable bounded-cardinality intent, not the earlier
image change. Operator-authored JSON and offline fixtures cannot satisfy it. A missing, ambiguous,
wrong-owner, wrong-container, wrong-image, wrong-limit, or unconverged observation stops progress.

Omit `--gate-evidence` for mutation stages. For a gate, supply an absolute path to a regular file
outside this repository (maximum 64 KiB):

```bash
python3 scripts/tokenplace_incident_drill.py --execute-stage "$GATE" \
  --plan "$PRIVATE_PLAN" --journal "$PRIVATE_JOURNAL_DIRECTORY" \
  --kubeconfig "$STAGING_KUBECONFIG" --gate-evidence "$PRIVATE_GATE_EVIDENCE"
```

Gate evidence uses this strict, versioned schema (the abbreviated digest below must be replaced by
the exact 64-character digest from the immutable plan):

```json
{
  "schema_version": 1,
  "run_id": "drill-20260910",
  "plan_digest": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "stage": "metrics-exit",
  "observed_from": "2026-09-10T11:45:00Z",
  "observed_until": "2026-09-10T12:00:00Z",
  "checks": {
    "authenticated_scrape": {
      "value": true,
      "observed_from": "2026-09-10T11:45:00Z",
      "observed_until": "2026-09-10T12:00:00Z",
      "source": "direct-authenticated-target"
    }
  }
}
```

The `checks` keys must exactly equal every metric in the selected plan action; the complete real
object therefore includes the other planned checks omitted from this compact example. Unknown or
missing fields are refused. All timestamps are RFC3339 UTC, ordered, not in the future, and the
top-level end time must be no more than five minutes old. The top-level interval must cover the
action duration; every check interval must be contained within it and cover its declared window.
Every individual check end time must also be no more than five minutes old; a fresh top-level end
time never makes an older contained check acceptable. Zero-duration gates may use a point-in-time
interval. A declared source must match exactly.
Booleans, strings, and finite JSON numbers are compared without boolean/number coercion.

Humans or external systems must supply real readiness, compute registration and polling,
encrypted request/response/retrieval/decryption, authenticated scrape, quota-validation, and
bounded observation results; the runner never infers or fabricates them. Evidence must contain no
payloads, tokens, encrypted bodies, prompts, responses, user identifiers, URLs, headers, or private
paths. The journal records only the SHA-256 digest, time bounds, and declared-source summary. A
validated non-mutating gate is published as one atomic completion record, so it cannot leave a new
intent pending. For a legacy or interrupted pending gate, an unchanged, still-fresh evidence file
is revalidated and completed. A different digest is refused while the original observation is
fresh. Once the recorded original observation is stale, the runner durably appends an `expired`
transition retaining its original digest and summary, then accepts only a new fully validated,
fresh evidence file in a separate atomic completion record. Interruption after `expired` is
retryable with that fresh file. This renewal performs no Kubernetes mutation and is available only
to immutable-plan gate actions; marker, mutation, rollback, and cleanup records retain their
intent and exact post-state rules. Reissue the same command to resume: a journaled completed stage
is a verified no-op, while a skipped stage, changed plan, changed coordinates, malformed evidence,
or marker collision is refused. Apply only the exact inverse of a completed mutation with:

```bash
python3 scripts/tokenplace_incident_drill.py --rollback-stage "$COMPLETED_MUTATION" \
  --plan "$PRIVATE_PLAN" --journal "$PRIVATE_JOURNAL_DIRECTORY" \
  --kubeconfig "$STAGING_KUBECONFIG"
```

On any interruption or threshold failure, stop forward execution and roll back completed mutations
in journaled reverse order. The recovery replacement inverse goes directly to the original healthy
baseline rather than back to the incident image; the stimulus inverse is baseline-idempotent, so
the last rollback records that the safe baseline is already present. Continue through every active
inverse until the original image, metrics mode and exact ServiceMonitor/Probe discovery labels are
restored. Never use the emergency fallback as an inverse: it remains a separately reviewed,
capability-revalidated emergency action.

After the original image and exact ServiceMonitor/Probe discovery labels are restored, and
`/livez` and `/healthz` are healthy, delete only the matching run-ID/digest marker. Repeating this
command reports the already-clean state without mutation:

```bash
python3 scripts/tokenplace_incident_drill.py --cleanup \
  --plan "$PRIVATE_PLAN" --journal "$PRIVATE_JOURNAL_DIRECTORY" \
  --kubeconfig "$STAGING_KUBECONFIG"
```

Cleanup refuses while any mutation remains active or when the exact Deployment image, replicas,
container, memory limit, metrics mode, discovery labels, `/livez`, or `/healthz` differs from the
recorded healthy baseline. Marker deletion is exact—there is no selector or prefix cleanup—and is
terminal only after baseline verification. A failure during mutation, rollback, health
verification, or marker deletion remains recoverable from the private append-only journal; it must
not be treated as a completed drill.

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
