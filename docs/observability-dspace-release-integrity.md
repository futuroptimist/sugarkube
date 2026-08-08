# DSPACE release-integrity alerting and synthetic runbook

For [issue #2329](https://github.com/futuroptimist/sugarkube/issues/2329),
[Sugarkube PR #2501](https://github.com/futuroptimist/sugarkube/pull/2501) added the
version-controlled staging rules, PagerDuty route, dashboard section, bounded synthetic consumer,
tests, and runbooks. [DSPACE PR #4806](https://github.com/democratizedspace/dspace/pull/4806)
added the result-file producer contract at runner revision
`92dad0cba4414aa111fd78bf03607c0aacc4043e`. The complete path is deployed and live-proven in
staging as recorded below. Production labels are part of the contract tests, but production
observability installation, live testing, and all production mutation remain unsupported and
unclaimed. The approved staging coordinate is derived from
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
is removed or a valid producer is restored. In staging, a five-minute systemd producer is enabled
on the trusted operator host and pinned to DSPACE runner revision
`92dad0cba4414aa111fd78bf03607c0aacc4043e`; Prometheus ingests fresh, bounded
`dspace_chat_synthetic_success` and `dspace_chat_synthetic_timestamp_seconds` series.

## Staging post-merge drills

Do **not** run these commands as part of repository validation and do not change DSPACE. An operator
may repeat this copy-pasteable drill with the repository-standard `sugar-staging` context. The
Prometheus `cluster="sugarkube-int"` value is a metric label, not a kubectl context.

```bash
set -euo pipefail
owner="dspace-2329-$(date -u +%Y%m%dT%H%M%SZ)-$RANDOM"
rule="${owner,,}"; rule="${rule//_/-}"
cleanup() {
  current="$(kubectl --context sugar-staging -n monitoring get prometheusrule "$rule" \
    -o jsonpath='{.metadata.labels.drill_owner}' 2>/dev/null || true)"
  test -z "$current" || test "$current" = "$owner"
  test -z "$current" || kubectl --context sugar-staging -n monitoring delete \
    prometheusrule "$rule" --wait=true --ignore-not-found=false
  ! kubectl --context sugar-staging -n monitoring get prometheusrule "$rule" >/dev/null 2>&1
}
trap cleanup EXIT
cat >"/tmp/${rule}.yaml" <<EOF
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: ${rule}
  namespace: monitoring
  labels:
    drill_owner: ${owner}
spec:
  groups:
    - name: ${rule}
      rules:
        - alert: DspaceBuildRevisionMismatch
          expr: label_replace(vector(1), "revision", "drill-mismatch", "", "")
          for: 1m
          labels: &labels
            application: dspace
            environment: staging
            cluster: sugarkube-int
            severity: critical
            expected_revision: 018687f5a7f4de45508c6e36eb28afb3e44da24d
            drill_owner: ${owner}
          annotations: &annotations
            summary: DSPACE drill revision mismatch
            current_revision: drill-mismatch
            remediation: Delete the exact owner-scoped temporary PrometheusRule.
            runbook_url: https://github.com/futuroptimist/sugarkube/blob/main/docs/observability-dspace-release-integrity.md#staging-post-merge-drills
        - alert: DspaceMixedBuildRevisions
          expr: label_replace(vector(1), "revision", "drill-multiple", "", "")
          for: 1m
          labels: *labels
          annotations:
            <<: *annotations
            summary: DSPACE drill mixed revisions
            current_revision: multiple
        - alert: DspaceChatSyntheticFailed
          expr: label_replace(vector(1), "state", "executed_failure", "", "")
          for: 1m
          labels: *labels
          annotations:
            <<: *annotations
            summary: DSPACE drill synthetic failure
            current_revision: unknown
EOF
kubectl --context sugar-staging -n monitoring apply -f "/tmp/${rule}.yaml"
test "$(kubectl --context sugar-staging -n monitoring get prometheusrule "$rule" \
  -o jsonpath='{.metadata.labels.drill_owner}')" = "$owner"
# Observe all three alerts in Prometheus and Alertmanager, then acknowledge their
# firing incidents in PagerDuty. The EXIT trap performs exact-name cleanup.
cleanup
trap - EXIT
```

Before the drill, prove there is exactly one scheduled producer, the reviewed external runner is
pinned to its full immutable revision, and the chart-rendered node-exporter DaemonSet has both the
`dspace-chat-textfile` host mount and
`--collector.textfile.directory=/var/lib/node_exporter/textfile_collector`. Verify the collector
exposes both bounded series. During the drill compare unrelated alerts and confirm they remain on
the null root. After exact-name cleanup, confirm PagerDuty receives a resolved event for every
firing incident and record timestamps without credentials or payload data.

### Sanitized staging verification record

On 2026-08-08, owner-scoped drill `dspace-2329-20260808T051818Z-1053` deliberately fired
`DspaceBuildRevisionMismatch`, `DspaceMixedBuildRevisions`, and `DspaceChatSyntheticFailed`.
All three reached firing in Prometheus and active state in Alertmanager; delivery to the configured
PagerDuty iPhone receiver, manual acknowledgement, and resolved delivery were confirmed. The other
two canonical alerts were not deliberately fired. All five canonical alerts were installed, loaded
by Prometheus, healthy, and inactive in the healthy steady state.

The exact temporary PrometheusRule was deleted by name and owner. After cleanup, its rule and alerts
were absent and the canonical observability verification passed. The healthy staging baselines were
unchanged: kube-prometheus-stack Helm revision 8 on chart `87.19.0`, and DSPACE Helm revision 28 at
application version `3.1.0` and source revision
`018687f5a7f4de45508c6e36eb28afb3e44da24d`. Revision 8, its live ConfigMap, and repository `main`
contained the same 44-panel dashboard, with canonical JSON SHA-256
`59cb188e015574a50a703c5000128d446896b1526f2d9fed9f7dde4ade32717b`. No production cluster,
Helm release, or workload was accessed or changed. This sanitized record intentionally excludes
credentials, routing keys, payloads, private addresses, and operator-local captures.

Rollback consists of disabling the single producer schedule, removing only `dspace-chat.prom`, and
reverting this staging observability release; removal of the producer alone intentionally makes the
missing-result state fire. No production deployment or route is provided or claimed.
