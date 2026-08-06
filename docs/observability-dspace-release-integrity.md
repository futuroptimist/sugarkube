# DSPACE release-integrity alerting and staging drills

## State and immutable coordinates

This repository is **ready**, but repository tests do not prove that rules are deployed or that a page
was delivered. Staging uses the finalized record
[`main-018687f-20260805T035722Z.json`](../deployment-evidence/dspace/staging/main-018687f-20260805T035722Z.json).
The generated values in `clusters/staging/observability/rules/` must be regenerated with
`scripts/generate_dspace_observability_rules.py`; CI proves agreement. Semantic tags are never release
identity. Production's finalized evidence is render/test input only: production observability remains
unsupported by the fail-closed Helm helper.

## Signals and diagnosis

All five alerts carry application, environment, cluster, severity, expected revision, a bounded
current revision (or `unknown`), remediation, and this stable runbook URL.

* **`DspaceBuildRevisionMismatch`** — compare `/build-info.json`, `dspace_build_info`, and each pod's
  image ID with finalized evidence. Runtime drift with a fresh passing synthetic is identity drift,
  not synthetic staleness. Reconcile the immutable release rather than a semantic tag.
* **`DspaceMixedBuildRevisions`** — inspect Deployment rollout status and pod start times. A healthy
  rollout may briefly contain two active revisions; the five-minute `for` period bounds settling.
  Beyond that, pause diagnosis and reconcile the stuck replica. Historical SHAs are not exported.
* **`DspaceDeploymentImagePinMismatch`** — compare the Deployment/pod tag and runtime image digest
  with evidence. This is workload-spec/image drift; `DspaceBuildRevisionMismatch` instead means the
  running application's identity endpoint disagrees. Either may fire alone.
* **`DspaceMetricsTargetDown`** — inspect ServiceMonitor target discovery, bearer-token Secret
  presence, TLS, and Prometheus target errors without printing credentials. If `/healthz` and public
  probes pass, treat this as scrape/authentication failure; if they also fail, investigate the app.
* **`DspaceChatSyntheticFailed`** — first inspect the last-run timestamp. Missing/stale data fails
  closed and is distinct from `dspace_chat_synthetic_success == 0`, an executed failure. For an
  executed failure compare public reachability, direct health, and provider dependency metrics:
  public-only failure suggests ingress; healthy app plus dependency failures suggests provider or
  configuration failure.

Rollback means restore the prior complete, finalized immutable coordinates through the DSPACE
release procedure in [the DSPACE guide](apps/dspace.md); do not use an unreviewed `helm rollback` or
mutable tag. Silence only after ownership and impact are understood.

## Non-mutating `/chat` producer contract

Sugarkube does not vendor or download DSPACE test code. An external scheduler must install a smoke
runner at an explicitly reviewed **full commit SHA**, run its `/chat` journey with mutation disabled
and an intercepted/isolated transport, and write only this JSON to a root-owned temporary file:

```json
{"schemaVersion":1,"journey":"/chat","passed":true,"mutationDisabled":true,"transport":"intercepted","completedAt":1785988800}
```

Publish atomically to a node-exporter textfile directory:

```bash
python3 scripts/dspace_chat_synthetic_metrics.py --result /run/dspace-chat/result.json \
  --output /var/lib/node_exporter/textfile_collector/dspace-chat.prom \
  --runner-revision 0123456789abcdef0123456789abcdef01234567
```

Schedule at least every five minutes. The publisher rejects mutable revisions, extra fields (including
keys, users, prompts, responses, URLs, request IDs, or errors), non-intercepted transport, mutation,
future results, and results over one hour old. Prometheus pages after 15 minutes without a timestamp.
Verify the two metric names and timestamp through Prometheus; never `cat` upstream logs containing
credentials. To roll back, disable the scheduler and remove only `dspace-chat.prom`; missing data then
fails closed. **Remaining prerequisite:** choose, security-review, install, and schedule the external
DSPACE smoke-runner artifact at a full commit SHA. Until that happens the alert correctly remains
firing/missing; continuous synthetic execution is not claimed.

## Post-merge staging drills

These drills require a change window and `sugar-staging`. They do not change the DSPACE release.
Choose a unique owner, label every temporary rule, and install a 15-minute cleanup trap. The alert
expressions use only constants, so no fake DSPACE series persist.

```bash
set -Eeuo pipefail
[[ "$(kubectl config current-context)" == sugar-staging ]]
owner="dspace-2329-$(date -u +%Y%m%dT%H%M%SZ)-$$"
name="${owner,,}"
cleanup() { kubectl -n monitoring delete prometheusrule "$name" \
  --ignore-not-found --wait=true; }
trap cleanup EXIT HUP INT TERM
python3 - "$name" <<'PY' | kubectl apply -f -
import json,sys
name=sys.argv[1]
alerts=["DspaceBuildRevisionMismatch","DspaceMixedBuildRevisions","DspaceChatSyntheticFailed"]
rules=[{"alert":a,"expr":"vector(1)","for":"1m","labels":{"application":"dspace","environment":"staging","cluster":"sugarkube-int","severity":"critical","expected_revision":"018687f5a7f4de45508c6e36eb28afb3e44da24d","revision":"unknown","drill_owner":name},"annotations":{"summary":"bounded #2329 staging drill","current_revision":"unknown","expected_revision":"018687f5a7f4de45508c6e36eb28afb3e44da24d","remediation":"remove the uniquely owned drill rule","runbook_url":"https://github.com/futuroptimist/sugarkube/blob/main/docs/observability-dspace-release-integrity.md"}} for a in alerts]
print(json.dumps({"apiVersion":"monitoring.coreos.com/v1","kind":"PrometheusRule","metadata":{"name":name,"namespace":"monitoring","labels":{"release":"kube-prometheus-stack","sugarkube.dev/drill-owner":name}},"spec":{"groups":[{"name":name,"rules":rules}]}}))
PY
sleep 90
kubectl -n monitoring get prometheusrule "$name" -o name
# Confirm all three alerts are firing and PagerDuty received the firing notifications.
cleanup
trap - EXIT HUP INT TERM
# Confirm all three resolve in PagerDuty and no resource with this owner remains:
! kubectl -n monitoring get prometheusrule -l "sugarkube.dev/drill-owner=$name" -o name | grep .
```

Run mismatch, mixed, and forced-failure drills separately if distinct PagerDuty incidents are required.
Before and after, confirm unrelated alerts are unchanged. The staging-only context guard, unique name,
exact label selector, exact-name deletion, and trap keep the exercise bounded; never run it against
production. Live acceptance still requires deploying the repository revision, installing the pinned
runner, observing each real rule, and manually confirming PagerDuty firing, acknowledgement, and
resolved delivery.
