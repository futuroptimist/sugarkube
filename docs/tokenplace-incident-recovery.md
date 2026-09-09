# token.place metrics-OOM and quota-exhaustion recovery

This is the fail-closed operator contract for the two canonical incident records linked from
[token.place PR #1763](https://github.com/futuroptimist/token.place/pull/1763).
It prepares the non-production drill tracked by
[Sugarkube issue #2779](https://github.com/futuroptimist/sugarkube/issues/2779); it does not
claim that drill passed.

## Safety boundary and evidence

Classification is read-only. Before mutation, obtain explicit approval and record the host,
kubeconfig, context, environment, namespace, Deployment, container, immutable image digest,
replicas, memory limit, and exact names of the ServiceMonitor and four Probes. Stop if any value is
missing, duplicated, mutable, ambiguous, or disagrees with the live Deployment and monitoring
inventory. Never paste a Secret, authentication header, source identity, raw path, ciphertext,
prompt, response, request identifier, public key, or private evidence location into output.

The evidence summary contains only timestamps, exact Kubernetes resource coordinates, immutable
artifact digest, numeric/status aggregates, gate results, rollback results, and whether cluster,
production, repository, or external state changed. Capture sanitized Deployment and container
termination fields, reason/exit code, aggregate event reasons, Probe and ServiceMonitor identities,
endpoint status classes, bounded route/cardinality and scrape-cost summaries, memory utilization,
restart counts, compute recovery, E2EE pass/fail, and cleanup pass/fail. Store sensitive raw evidence
only in the separately approved private system and do not print its location.

Every mutation must first print the exact kind/name/namespace and inverse operation. Keep the
captured, resource-version-free pre-mutation manifest private for rollback. A missing or non-unique
resource is a hard stop. Record explicitly: classification changed no state; a completed drill
changed only staging cluster state temporarily; production, repository, and external state did not
change. Repository updates and tracker comments happen only after evidence exists; this runbook
never closes an issue automatically.

## Read-only classification

Confirm `/livez` and `/healthz` independently. An unready Pod is **not** OOM proof. Metrics-OOM
classification requires the affected container's `lastState.terminated.reason` to equal
`OOMKilled` and exit code to equal `137`. Quota classification distinguishes an application-wide
outage from 429s on the exact `GET /` and `GET /api/v1/meta` routes while health remains available.

Inspect effective limiter limits, exact route/method exemptions, proxy-aware identity mode, and
storage type using names and boolean/status summaries only. Do not read or display secret values or
source identities. Run `python3 scripts/validate_probe_quotas.py --environment staging`; its
declarative inventory is authoritative for probe route, method, shared bucket, fanout, multiplier,
limits, safety margin, and unlimited operational endpoints.

For metrics-OOM, feature-detect the deployed digest's documented degraded-metrics setting without
guessing an environment variable. Use it only when the artifact documents it. Otherwise remove the
Prometheus selector label from **only** the named token.place ServiceMonitor, with the inverse
exact-name label restoration printed first. Never change a Probe. Keep scraping paused until the
authenticated scrape, bounded route labels/cardinality and cost, memory, restart/OOM, compute, and
functional gates pass.

For quota exhaustion, remove the Prometheus selector label from **only** the named root and metadata
Probe resources. Restore that label to those exact resources for rollback. Never change `/livez` or
`/healthz`. Validate exact route/method semantics against the quota inventory both before pause and
before each restoration.

## Replacement, state loss, and rollback

Print the previous immutable digest, replicas, memory limit, and exact Deployment/container before
deploying or replacing. A container restart loses process-local relay counters and registrations,
but preserves Pod-lifetime `emptyDir` multiprocess metric files. Pod replacement loses both process
state **and** that `emptyDir`; therefore a mere container restart does not clear stale multiprocess
files. Either action requires explicit state-loss authorization. Never restart merely to reset
quota counters.

After replacement, require: workload ready within 10 minutes; every replica has the exact digest;
zero new restarts and no OOM termination; compute re-registration and two successful lease polls;
then a real encrypted request, compute response, retrieval, and client-side decryption. Synthetic
registration or plaintext relay inspection is not a substitute. Roll back the Deployment to the
printed prior immutable digest if readiness or identity misses the deadline, any restart/OOM occurs,
compute does not recover in 5 minutes, or E2EE fails.

Restoration order is fixed:

1. deploy/replace;
2. workload readiness and exact artifact identity;
3. compute registration and polling;
4. encrypted request/response/retrieval/decryption;
5. restore root Probe, observe 10 minutes;
6. restore metadata Probe, observe 10 minutes;
7. restore application ServiceMonitor last, observe 30 minutes;
8. perform exact cleanup and update the canonical incident records and trackers.

At each Probe gate, roll back that exact Probe label if any health failure, more than 1% 429 or 5xx
responses over five minutes, any restart/OOM, or compute/E2EE regression occurs. At the metrics gate,
roll back only the ServiceMonitor if the authenticated target is not up within two scrape intervals,
new unbounded route labels appear, series/scrape cost exceeds the reviewed baseline by 20%, memory
exceeds 80% of its limit for five minutes, or any restart/OOM occurs. `/livez` and `/healthz` must
remain continuously covered. Do not proceed merely because a bounded window elapsed.

## Step 14b staging drill

Choose a unique DNS-safe drill ID and an existing private evidence location. Run the generator twice,
once per class, replacing every placeholder with reviewed staging coordinates:

```bash
python3 scripts/tokenplace_incident_runbook.py --mode metrics-oom --host staging.token.place --kubeconfig "$KUBECONFIG" --context sugar-staging --environment staging --namespace tokenplace --deployment tokenplace --container REPLACE_CONTAINER --image 'REPLACE_REGISTRY/REPLACE_IMAGE@sha256:REPLACE_64_HEX' --replicas REPLACE_COUNT --memory-limit REPLACE_LIMIT --service-monitor REPLACE_EXACT_SERVICEMONITOR --root-probe blackbox-tokenplace-staging-root --metadata-probe blackbox-tokenplace-staging-metadata --livez-probe blackbox-tokenplace-staging-livez --healthz-probe blackbox-tokenplace-staging-healthz --drill-id "drill-REPLACE_UNIQUE"
```

Repeat with `--mode quota-exhaustion`. This dry run touches no cluster and emits no host, kubeconfig,
image, credentials, identities, request data, or evidence path. Review its pause set, preserved set,
mandatory gate order, state-loss declarations, and exact rollback coordinates. `--execute` performs
only a read-only Deployment lookup and then refuses mutation; live mutations remain human-reviewed
commands until Step 14b validates the contract.

The live drill must use unique temporary workload names labeled with the drill ID; it must not alter
the stable Deployment merely to manufacture either incident. On resume, rediscover only resources
with that exact ID, compare their recorded phase, and continue at the first incomplete gate. Refuse
multiple matches. Cleanup restores each exact Probe/ServiceMonitor label from its recorded inverse,
deletes only exact-ID temporary resources, verifies they are absent, reruns the quota validator, and
confirms health coverage. Cleanup is required after both success and rollback.

Acceptance evidence is one durable schema-version-1 JSON summary per mode containing the drill ID,
UTC gate timestamps, sanitized coordinates and digest, OOM reason/137 proof or exact-route 429 proof,
pause/preserve selection, replacement type and state-loss approval, readiness and restart counts,
compute registration/two polls, encrypted E2EE result, ordered restoration observations, metric cost
and memory aggregates, rollback/cleanup results, and four state-changed booleans. Do not attach raw
requests or private paths. A human then links these summaries to #2779 and the canonical records;
the live staging drill remains Step 14b until all acceptance evidence is reviewed.
