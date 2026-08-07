# DSPACE release-integrity alerts

This runbook covers repository support for the five staging DSPACE alerts. The approved staging
coordinate is read from the finalized [release evidence](../deployment-evidence/dspace/staging/main-018687f-20260805T035722Z.json),
not from the semantic application tag. Production coordinates are tested as a contract only;
Sugarkube does **not** currently install production observability.

## Shared triage

Open the Grafana **DSPACE release integrity** row and record the expected revision, active revisions,
image-pin agreement, target health, synthetic result, and freshness. Use `just dspace-release-verify
env=staging ...` for an authoritative, non-mutating runtime verification. A revision label is always
the bounded active/approved revision, `mixed`, or `unknown`; request data and raw errors are never
metrics labels.

## DspaceBuildRevisionMismatch

After the ten-minute settling window, compare `/build-meta.json`, the pod's OCI revision annotation,
and finalized evidence. A present but different revision is runtime drift; `unknown` means identity
telemetry is missing. Restore the approved digest with the guarded DSPACE deployment workflow or
roll back to finalized evidence. Do not “fix” the alert by changing the expected SHA.

## DspaceMixedBuildRevisions

Check Deployment progress and ReplicaSets. Mixed revisions for less than the alert's ten-minute
`for` period are an ordinary settling rollout. If it fires, identify stuck old replicas and either
finish the approved rollout or use the documented guarded rollback. Never delete pods merely to
silence the signal before determining why the controller retained both revisions.

## DspaceDeploymentImagePinMismatch

This compares active pod `imageID` digests with the approved immutable digest. It is distinct from
runtime identity: a digest mismatch means the Deployment/pod image coordinate drifted; a build
revision mismatch with the right digest means the artifact reports the wrong runtime identity.
Inspect the Helm stored values and Deployment template, then redeploy the finalized digest.

## DspaceChatSyntheticFailed

The `synthetic_state` label distinguishes `executed_failure` from `missing_or_stale`. First inspect
the timestamp: stale telemetry is a scheduler/exporter problem, not evidence that `/chat` executed
and failed. For an executed failure, verify public HTTP/TLS and then run the pinned smoke runner with
intercepted/isolated transport and mutation disabled. Separate public route failures from provider
or configuration failures by comparing the direct build identity and provider reported by
`dspace_runtime_verifier.py`. Never supply, require, or log user credentials.

### Producer installation and schedule

The repository consumer contract expects two gauges, with only `application`, `environment`, and
the active full `revision` as labels:

```text
dspace_chat_synthetic_success{application="dspace",environment="staging",revision="<40-hex>"} 1
dspace_chat_synthetic_timestamp_seconds{application="dspace",environment="staging",revision="<40-hex>"} <unix-seconds>
```

An external scheduler is still required. Pin the DSPACE smoke-runner artifact by immutable commit
and verified digest; cloning a branch or downloading mutable code at runtime is forbidden. Schedule
it at most every five minutes, invoke `dspace_runtime_verifier.py verify` with its documented named
`--smoke-runner` contract, isolated/intercepted transport, and mutation disabled, then atomically
publish the bounded result to the node-exporter textfile directory:

```bash
python3 scripts/dspace_synthetic_metrics.py \
  --result /run/dspace-synthetic/runtime-verification.json \
  --output /var/lib/node_exporter/textfile_collector/dspace-chat-synthetic.prom
```

The publisher refuses common credential environment variables. Configure Prometheus to collect that
textfile through the already-managed node exporter, confirm both gauges and their label set in
Grafana, and stop/remove the scheduler plus its single `.prom` file to roll back. Missing data fails
closed after 15 minutes. Until the pinned external runner, scheduler, and textfile mount are installed
and verified in staging, the repository is **ready**, not continuously deployed or operationally
proven.

## DspaceMetricsTargetDown

This alert covers missing discovery and `up == 0`. Inspect ServiceMonitor selection, bearer-token
Secret mounting, NetworkPolicy, and `/metrics`. A scrape failure can coexist with a healthy public
application; compare blackbox/public health before treating it as an application outage. Conversely,
a healthy scrape does not prove `/chat` works.

## Post-merge staging drills

Run only against context `sugar-staging`. Use a unique owner value and a temporary `PrometheusRule`
in `monitoring`; do not change the DSPACE release. The safe pattern below makes cleanup select the
exact name **and** owner, so it cannot remove another drill:

```bash
export DRILL_ID="dspace-2329-$(date -u +%Y%m%dT%H%M%SZ)-$$"
test "$(kubectl config current-context)" = sugar-staging
trap 'kubectl -n monitoring delete prometheusrule "$DRILL_ID" \
  --field-selector "metadata.name=$DRILL_ID" --ignore-not-found' EXIT
```

Create bounded temporary rules with labels `drill_owner="$DRILL_ID"`, `environment="staging"`, and
`cluster="sugarkube-int"`: (1) replace the expected revision only in the temporary mismatch
expression; (2) use two `label_replace(vector(1), "revision", ...)` series for mixed revisions; and
(3) set the temporary synthetic-success series to zero with a current timestamp. Give each rule a
15-minute maximum lifetime annotation and the production-rejecting namespace/context guards above.
Confirm each exact alert in Prometheus and Alertmanager, then confirm PagerDuty firing and resolved
notifications. Delete each rule and wait for resolution before the next. Finally run:

```bash
test -z "$(kubectl -n monitoring get prometheusrule "$DRILL_ID" --ignore-not-found -o name)"
kubectl -n monitoring get prometheusrules -l "drill_owner=$DRILL_ID" -o name | test "$(wc -l)" -eq 0
```

Do not silence, edit the installed rules, route unrelated alerts, or target production. Live
PagerDuty receipt/resolution, all three simulated firings, cleanup, and the external synthetic
installation remain explicit post-merge acceptance steps.
