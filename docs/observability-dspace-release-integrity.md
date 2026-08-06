# DSPACE release-integrity alerting and synthetic runbook

This repository defines the staging rules and PagerDuty route for issue #2329. It does **not**
prove that Helm has deployed them or that PagerDuty has delivered them. Production labels are part
of the contract tests, but production observability installation and all production mutation remain
unsupported. The approved staging coordinate is derived from
[`main-018687f-20260805T035722Z.json`](../deployment-evidence/dspace/staging/main-018687f-20260805T035722Z.json);
the production contract is checked against
[`main-1a31a56-20260801T093443Z.json`](../deployment-evidence/dspace/prod/main-1a31a56-20260801T093443Z.json).
Semantic tags are descriptive only and are never deployment identity.

## Signals and triage

### DspaceBuildRevisionMismatch

Compare `dspace_build_info` with the approved full revision. An absent identity is `unknown`; a
reported different revision is runtime drift. Check `/build-meta.json`, pod image IDs, and the final
evidence. Restore the digest-pinned release rather than editing the approved series.

### DspaceMixedBuildRevisions

A normal rollout can briefly expose two revisions, so the alert waits ten minutes. After that,
inspect Deployments, ReplicaSets, readiness, and termination. Pause the rollout and converge every
serving replica; do not delete unrelated workloads.

### DspaceDeploymentImagePinMismatch

This compares active container `image_id` values with the approved digest. A mismatch here is
Deployment/pod-image drift. A matching digest with a wrong `dspace_build_info` revision is runtime
identity drift instead; quarantine that artifact and investigate provenance.

### DspaceChatSyntheticFailed

First distinguish freshness from execution: `dspace_chat_synthetic_success == 0` means a run
executed and failed; a missing timestamp or age over 900 seconds means the producer is stale and
fails closed. For an executed failure, compare public `/chat` reachability with direct health and
then inspect the configured provider. A healthy app with failed chat usually points to provider or
configuration failure. Never print API keys, prompts, responses, users, sessions, or raw errors.

### DspaceMetricsTargetDown

Inspect Prometheus target discovery, ServiceMonitor labels, bearer Secret reference, and network
policy. A failed scrape is not proof the application failed: compare `/healthz`, `/livez`, and public
blackbox probes. Conversely, an `up` target does not prove `/chat` works.

## Synthetic producer/consumer contract

Sugarkube supplies a bounded textfile consumer, not the external smoke runner or scheduler. Install
`scripts/dspace_chat_synthetic_metrics.py` on a trusted staging operator host that has a
node-exporter textfile directory. Pin the external DSPACE smoke runner to a reviewed **full commit
SHA** and install it from an immutable artifact out of band; never clone a branch or download code
at runtime. Schedule it at least every ten minutes with intercepted/isolated transport and mutation
disabled. It must write exactly this schema without secrets or free-form diagnostic fields:

```json
{"schemaVersion":1,"journey":"/chat","passed":true,"executedAt":1785988800,"runnerRevision":"0123456789abcdef0123456789abcdef01234567","transport":"intercepted","mutationEnabled":false}
```

Publish atomically after the runner succeeds:

```bash
python3 scripts/dspace_chat_synthetic_metrics.py \
  --result /run/dspace-chat/result.json \
  --output /var/lib/node_exporter/textfile_collector/dspace-chat.prom \
  --runner-revision "$PINNED_DSPACE_SMOKE_RUNNER_SHA" --environment staging
```

Verify both metrics in Prometheus and check timestamp age. A malformed result leaves the prior file
untouched, which becomes stale and alerts. Roll back by disabling only this scheduler and removing
only `dspace-chat.prom`; the missing-series branch deliberately continues to alert until the route
is removed or a valid producer is restored. Remaining live prerequisite: select, review, pin,
install, and schedule a DSPACE-owned runner that implements the exact isolated contract above.

## Staging post-merge drills

Do not change the DSPACE Helm release. Use a unique owner such as
`dspace-2329-$(date -u +%Y%m%dT%H%M%SZ)-$RANDOM`. Create a temporary `PrometheusRule` in the
`monitoring` namespace whose name and every rule carry `drill_owner="$owner"`; copy one production
expression at a time and replace only its input with bounded `vector()` test series. Use full
staging labels and the real alert name. Simulate (1) a non-approved revision, (2) two revision
series, and (3) a zero synthetic result with a current timestamp. Wait through each rule's `for`,
verify firing in Prometheus/Alertmanager, then remove **only** the exact owned object:

```bash
owner="dspace-2329-$(date -u +%Y%m%dT%H%M%SZ)-$RANDOM"
rule="${owner,,}"; rule="${rule//_/-}"
kubectl --context sugarkube-int -n monitoring apply -f "/tmp/${rule}.yaml"
kubectl --context sugarkube-int -n monitoring get prometheusrule "$rule" \
  -o jsonpath='{.metadata.labels.drill_owner}' | grep -Fx "$owner"
kubectl --context sugarkube-int -n monitoring delete prometheusrule "$rule" \
  --wait=true --ignore-not-found=false
! kubectl --context sugarkube-int -n monitoring get prometheusrule "$rule"
```

The temporary manifest must set `metadata.labels.drill_owner`, contain no Secret, use at most two
series, and have a unique name. Abort if the ownership read-back differs. Never use a label selector
for cleanup. Confirm PagerDuty receives firing and resolved events for every allowlisted alert,
while an unrelated test alert remains at the null root. Record screenshots/timestamps and confirm
production received nothing. These live results are required before #2329 can be closed.
