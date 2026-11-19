# democratized.space (dspace) on Sugarkube

## Current v3.1.0 release entry point

Use the existing [DSPACE release runbook](https://github.com/democratizedspace/dspace/blob/main/docs/ops/sugarkube-release.md)
for publication order, staging-before-production deployment and rollback, and the
[v3.1 QA checklist](https://github.com/democratizedspace/dspace/blob/main/docs/qa/v3.1.md)
for acceptance criteria. The generic `just app-*` recipes below are implemented and preferred;
`dspace-oci-*` recipes are compatibility shims with the same guarded requirements.

DSPACE source metadata prepares application `3.1.0` with provisional chart `3.1.3`. This is not
published-artifact or deployment evidence. Candidate selection and live sign-offs remain separate.
The existing semantic `v3.1.0` image coordinate is occupied; follow the upstream
[source/artifact reconciliation](https://github.com/democratizedspace/dspace/blob/main/docs/releases.md#application-versions-and-chart-versions)
and stop pending a release-owner decision. Do not overwrite artifacts, fabricate a release
manifest, reuse historical evidence as a new approval, or weaken publication guards.

The current candidate requires fresh-user default provider `token-place`, model
`qwen3-8b-instruct`, staging origin `https://staging.token.place` and production origin
`https://token.place`. The committed production overlay still selects the historical Llama model,
and the existing chart/image pins describe earlier targets. A separately reviewed configuration
change must reconcile those inputs before v3.1.0 promotion; this documentation does not change them.

| Environment | Default operator host | Grafana                                                                                                               |
| ----------- | --------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Staging     | `sugarkube3`          | [Staging observability](http://sugarkube3:30300/d/sugarkube-staging-observability/sugarkube-staging-observability)    |
| Production  | `sugarkube0`          | [Production observability](http://sugarkube0:30300/d/sugarkube-prod-observability/sugarkube-production-observability) |

Run Bash examples from a reviewed Sugarkube checkout with explicit environment kubeconfigs.
Hostnames do not prove cluster identity; production promotion also requires staging read access.
Dashboard links alone do not prove reachability, complete panels or a successful soak. Follow
[observability operations](../observability-operations.md),
[DSPACE release integrity](../observability-dspace-release-integrity.md) and
[encrypted completion observability](../encrypted-completion-observability.md), and retain the
required live evidence before production approval. Intercepted browser checks do not establish
live token.place completion or satisfy the entire QA checklist.

The following incident sections preserve earlier coordinates and constraints. They do not select
the current candidate or authorize repeating their operations. Continue at [Artifact model](#artifact-model)
for the general procedure.

<a id="311-staging-first-promotion-preparation-no-operation-authorized"></a>

## Historical 3.1.1 staging-first promotion preparation (no operation authorized)

`docs/apps/dspace.promotion-target.json` is the reviewed, schema-v2 machine-readable preparation target for application `3.1.1` and chart `3.1.2`. It records the immutable image and chart release coordinates: explicit application and chart source revisions, the branch image tag, OCI image and chart manifest digests, and semantic release tag. A semantic image tag is never a deployment coordinate. The staging chart pin advances so a later approved staging candidate can exercise chart `3.1.2`; production pins and finalized baselines remain unchanged.

The read-only planner accepts independently produced, bounded JSON reports and a local chart archive:

```bash
python3 scripts/dspace_promotion_plan.py \
  --artifact-report /reviewed/dspace-3.1.1-artifacts.json \
  --source-report /reviewed/dspace-3.1.1-metrics-source.json \
  --classifier-report /home/pi/operator-evidence/dspace-prod-classifier.json \
  --failed-reconciliation /home/pi/operator-evidence/dspace-prod-metrics-reconcile-20260813T072927Z/reconciliation.json \
  --historical-staging-evidence deployment-evidence/dspace/staging/main-018687f-20260805T035722Z.json \
  --chart-archive /reviewed/dspace-3.1.2.tgz
```

The independently generated artifact report must prove the exact image digest, Linux/ARM64 availability, OCI source revision, chart name/version/application version, OCI manifest digest, source revision, and release tags. It also records and binds the distinct chart-layer/archive digest to those reviewed target coordinates. The source report lists exactly the six privacy-safe `dspace_*` definitions and states that it contains no raw metrics. The classifier report is bounded: two healthy targets, zero scrape errors, public `401`, Secret existence without reading its value, two samples for each named default Node family, zero samples for every required application family, the established classification, and `clusterMutationPerformed=false`. Unknown fields (including Secret values or raw payloads), partial families, unhealthy targets, and mutation claims fail closed.

Before creating the DSPACE 3.1.1 staging candidate, run all repository-owned read-only
authenticated metrics prerequisites against staging. These commands check that the existing Secret
and key are selected without returning the Secret value, verify the DSPACE contract directly, and
then discover and verify every application configured for staging:

```bash
just observability-app-metrics-secret-check app=dspace env=staging
just observability-app-metrics-verify app=dspace env=staging
just observability-verify env=staging
```

All three checks must pass before candidate creation is considered. They do not create a candidate,
approve a release, mutate either cluster, or authorize deployment; candidate creation and deployment
remain separate, explicitly authorized future operations.

The planner independently validates the preserved failed reconciliation against the reviewed 3.0.1 maintenance tuple. It recognizes finalized application 3.1.0/chart 3.1.1 staging evidence only as historical and emits `historicalStagingEvidenceAuthorizesTarget=false`. It renders staging and eventual production locally only after verifying the local archive bytes against the artifact report's validated archive digest, never against the distinct OCI manifest digest, with two replicas, `image.pullPolicy=Always`, and `main-22f506e`. It rejects rendered Secrets, staging values in production, semantic image tags, and `--reuse-values`. Its sanitized JSON contains no credentials or raw metrics and an empty `mutationCommands` list. It never runs Helm upgrade, kubectl, rollout, Secret mutation, artifact publication, approval creation, or evidence finalization.

### Required future sequence

This preparation is not approval or deployment evidence. A future operator must, in order:

1. Record genuine operator approval metadata for the exact 3.1.1/3.1.2 coordinates.
2. Create a fresh staging candidate for those coordinates and deploy it through the existing guarded release-manifest machinery.
3. Prove exactly two Ready replicas at the reviewed image digest; matching runtime and frontend source identity; public/direct agreement; and the intended eventual production provider `openai`.
4. Run a bounded remote `/chat` smoke and prove two healthy authenticated Prometheus targets with no scrape errors. Prove all six required families: `dspace_build_info`, `dspace_dchat_requests_total`, `dspace_dependency_requests_total`, `dspace_http_request_duration_seconds_bucket`, `dspace_http_requests_total`, and `dspace_instrumentation_up`. Where counters require traffic, capture a real server-observed chat/dependency journey without response bodies, tokens, Secret values, or raw metrics payloads.
5. Finalize fresh, non-overwritable staging evidence only after every check succeeds. The optional `--staging-proof` input accepts it only when every coordinate, `openai`, identity, metrics, and smoke result matches.
6. Only a separate future repository task may add a guarded, one-shot successor to production Helm revision 10. The old classifier and historical staging evidence cannot authorize it.

The existing `dspace-prod-metrics-pull-policy-recover` operation remains ineligible for this incident: application 3.0.1 cannot supply the required metrics. Preserve its preflight and verifier unchanged; do not rerun, weaken, bypass, or repurpose it as an application promotion. Do not roll back or uninstall Helm, and do not read, rotate, or delete the metrics Secret. Issues #2325 and #2329 remain closed unless a human chooses otherwise, and issue #2408 is separate and must not be modified or conflated.

The historical preparation above remains scoped to its recorded 3.1.1/OpenAI target; it is not the v3.1.0/token.place release contract.

<a id="production-authenticated-metrics-chart-maintenance"></a>

## Historical production authenticated metrics chart maintenance

This guarded operation is a **chart-only maintenance upgrade** from immutable DSPACE chart 3.0.2
to 3.0.3 so authenticated production metrics can be enabled. It is not an application promotion:
application 3.0.1, source `1a31a569aff2dbeb238e8c2688b9e85140d2077d`, image
`main-1a31a56` and its digest, provider `openai`, two replicas, routing, and credentials remain
unchanged. The finalized 3.0.2 production evidence remains historical, byte-for-byte unchanged;
the separately reviewed chart target is `docs/apps/dspace.prod-metrics-chart-target.json`.

Run from `sugarkube3` with the externally managed API tunnel on `127.0.0.1:16443`. Supply the
explicit production kubeconfig. The operation checks context `sugar-prod`, production cluster
identity, the genuine finalized baseline, exact live revision/chart/pods, the metrics Secret
contract without reading its value, strict values drift, the digest-qualified render, and fresh OCI
provenance before reserving evidence or mutating Helm. Do not install or rotate
`dspace-prod-metrics-token` as part of this operation.

The currently verified transition is revision 9 to 10. Tooling derives revision 9 from the baseline
and requires exactly one revision advance; it does not blindly hard-code either revision. Use a
fresh, nonexisting evidence destination and the executable remote `/chat` smoke runner:

```bash
just dspace-prod-metrics-reconcile \
  baseline_manifest=deployment-evidence/dspace/prod/main-1a31a56-20260801T093443Z.json \
  maintenance_target=docs/apps/dspace.prod-metrics-chart-target.json \
  evidence="$FRESH_NONEXISTING_EVIDENCE" \
  smoke_runner="$DSPACE_SMOKE_RUNNER" \
  kubeconfig="$HOME/.kube/config-sugarkube-prod" \
  confirm="dspace:prod:1a31a569aff2dbeb238e8c2688b9e85140d2077d"
```

New deployment, reconciliation, recovery, and rollback output pins the application image as
`repository:tag@sha256:digest` using the reviewed manifest identity. Deployment and redeployment
use one private manifest snapshot for validation, rendering, application, and finalization. Runtime
verification requires that pin in both the Deployment template and its pods; a matching current
`imageID` alone does not protect a future restart. Historical finalized evidence remains readable.
The exact legacy reconciliation baseline remains tag-only on input and migrates to pinned output.

The current evidence contract requires the observed `imageID` digest to equal the approved index
digest. A distinct platform digest is rejected: accepting index/platform equivalence would require
additional authenticated platform membership evidence, which this change does not introduce.

### One-time production pull-policy recovery

The failed revision-10 reconciliation evidence is immutable and remains failed. After this change is
merged, a separately authorized operator may repair only the reviewed incident state: revision 10,
chart 3.0.3, and complete approved values with the sole delta
`image.pullPolicy=IfNotPresent` and the historical tag-only image coordinate. Recovery also migrates
that coordinate to the reviewed digest pin. The legacy runtime exception is restricted to the exact
approved 3.0.3 production tuple at revision 10 during recovery preflight; revision 11 must be pinned.
This is **not** a rerun of
`dspace-prod-metrics-reconcile`. The command fails closed on any other revision, chart, invocation,
pod, image, Secret contract, provenance, or values state; it performs at most one digest-qualified
upgrade to revision 11 and writes a new private evidence record.

Do not run this during development. Following explicit production authorization, use exactly:

```bash
just dspace-prod-metrics-pull-policy-recover \
  failed_evidence=/private/evidence/dspace-prod-metrics-failed.json \
  maintenance_target=docs/apps/dspace.prod-metrics-chart-target.json \
  recovery_evidence=/private/evidence/dspace-prod-metrics-pull-policy-recovery.json \
  smoke_runner="$HOME/dspace/scripts/run-remote-chat-smoke.mjs" \
  kubeconfig="$HOME/.kube/config-sugarkube-prod" \
  confirm=dspace:prod:recover-revision-10-pull-policy
```

The failed and recovery evidence paths must be private; the recovery destination must not exist.
Never retry, roll back, uninstall, rotate Secrets, or issue a second Helm mutation automatically if
the recovery fails. Preserve its failed-stage evidence and investigate the sanitized diagnostics.

The command uses only the exact digest-qualified 3.0.3 OCI chart, the complete committed production
values chain, and an invocation-bound opaque Helm description; it never uses `--reuse-values`.
Afterward it proves replacement Ready pods retain the exact image digest, runs strict runtime,
frontend, provider, remote `/chat`, and production metrics verification, and finalizes evidence.
Any failure after reservation preserves failed evidence. Review that evidence and live Helm history
before any further mutation; never automatically rerun, uninstall, roll back, delete, or rotate the
Secret.

<a id="production-helm-reconciliation-for-application-301"></a>

## Historical production Helm reconciliation for application 3.0.1

This section **prepares but does not execute** the incident reconciliation tracked by
Sugarkube issue #2325. Keep the production Helm freeze in place throughout. The reviewed,
machine-readable input is `docs/apps/dspace.prod-recovery-coordinates.json`: schema 2 keeps the
application/image revision in `sourceRevision` and independently records the recovery chart's
revision in `chartSourceRevision`. The `v3.0.1` semantic tag is corroborating metadata only; never
pass it to Helm, publish it, or use it as an image coordinate. The chart OCI manifest digest is not
the downloaded chart archive's SHA-256.

### 1. Repository preparation (already performed by this change)

Review the recovery input, production chart pin, production values chain, and immutable image pin.
The two kubeconfigs must name different files and clusters. These commands are read-only:

```bash
RECOVERY=docs/apps/dspace.prod-recovery-coordinates.json
STAGING_KUBECONFIG="$HOME/.kube/config-sugarkube-staging"
PROD_KUBECONFIG="$HOME/.kube/config-sugarkube-prod"
DSPACE_SMOKE_RUNNER="$HOME/dspace/scripts/run-remote-chat-smoke.mjs"
test "$STAGING_KUBECONFIG" != "$PROD_KUBECONFIG"
test -r "$STAGING_KUBECONFIG" && test -r "$PROD_KUBECONFIG"
test -x "$DSPACE_SMOKE_RUNNER"
python3 scripts/app_config.py json --app dspace --env prod
jq -e '.schemaVersion == 2 and .applicationVersion == "3.0.1" and
  .sourceRevision == "1a31a569aff2dbeb238e8c2688b9e85140d2077d" and
  .chartSourceRevision == "62da11005354e9f9a89c2e58584cdce4c8ec35aa" and
  .imageTag == "main-1a31a56" and
  .imageDigest == "sha256:23dbc573377549136c1f10b05706b3c176ffbabaf04a3194381a24752104a401" and
  .chartVersion == "3.0.3" and
  .chartDigest == "sha256:6ee663c426673bc0e516ed8f8b0ab11a918d2f2bb81fc9047b3eb37b78329f5c"' "$RECOVERY"
```

Before encoding approval, inspect the immutable DSPACE 3.0.1 application contract at revision
`1a31a569aff2dbeb238e8c2688b9e85140d2077d` and run its contract tests. The recovery behavior is
OpenAI-first, so set `EXPECTED_PROVIDER=openai` only if that immutable source and its executable
remote `/chat` runner confirm it. Stop if they say `token-place`, if the runner is unavailable, or
if any coordinate differs; do not edit evidence to make it agree.

### 2. Operator-supplied approval and staging

Approval identity and UTC time come from the real maintenance approval record. They are not stored
in the recovery input. Generate both candidates from that same input:

```bash
APPROVED_AT='<YYYY-MM-DDTHH:MM:SSZ-from-approval>'
APPROVED_BY='<operator-or-review-record>'
EXPECTED_PROVIDER=openai
mkdir -p deployment-candidates/dspace
# Keep the shared staging pin unchanged while selecting the independently
# approved 3.0.3 production pin for this recovery only.
RECOVERY_CONFIG=$(mktemp)
RECOVERY_VERSION=$(mktemp)
trap 'rm -f "$RECOVERY_CONFIG" "$RECOVERY_VERSION"' EXIT
printf '%s\n' 3.0.3 >"$RECOVERY_VERSION"
python3 - "$RECOVERY_CONFIG" "$RECOVERY_VERSION" <<'PY'
from pathlib import Path
import sys

source = Path("docs/examples/apps/dspace.env").read_text(encoding="utf-8")
old = "SUGARKUBE_VERSION_FILE_STAGING=docs/apps/dspace.staging.version"
new = f"SUGARKUBE_VERSION_FILE_STAGING={Path(sys.argv[2]).resolve()}"
if source.count(old) != 1:
    raise SystemExit("expected exactly one staging version-file assignment")
Path(sys.argv[1]).write_text(source.replace(old, new), encoding="utf-8")
PY
python3 scripts/app_config.py json --app dspace --env staging \
  --config "$RECOVERY_CONFIG"
python3 scripts/dspace_release_manifest.py candidate --upstream "$RECOVERY" \
  --output deployment-candidates/dspace/recovery-staging.json --environment staging \
  --provider "$EXPECTED_PROVIDER" --approved-at "$APPROVED_AT" --approved-by "$APPROVED_BY"
python3 scripts/dspace_release_manifest.py candidate --upstream "$RECOVERY" \
  --output deployment-candidates/dspace/recovery-prod.json --environment prod \
  --provider "$EXPECTED_PROVIDER" --approved-at "$APPROVED_AT" --approved-by "$APPROVED_BY"
python3 scripts/dspace_release_manifest.py validate \
  --manifest deployment-candidates/dspace/recovery-staging.json
python3 scripts/dspace_release_manifest.py validate \
  --manifest deployment-candidates/dspace/recovery-prod.json
```

Use the guarded staging recipe, then retain and review its non-overwritable finalized evidence:

```bash
just app-deploy app=dspace env=staging tag=main-1a31a56 \
  config="$RECOVERY_CONFIG" \
  manifest=deployment-candidates/dspace/recovery-staging.json \
  smoke_runner="$DSPACE_SMOKE_RUNNER" kubeconfig="$STAGING_KUBECONFIG"
STAGING_EVIDENCE=$(python3 scripts/dspace_release_manifest.py evidence-path \
  --manifest deployment-candidates/dspace/recovery-staging.json)
python3 scripts/dspace_release_manifest.py validate --final --manifest "$STAGING_EVIDENCE"
python3 scripts/dspace_release_manifest.py staging-gate \
  --manifest deployment-candidates/dspace/recovery-prod.json \
  --staging-evidence "$STAGING_EVIDENCE"
```

That gate must prove application version, immutable image tag/digest, chart version/digest, both
source revisions, OpenAI provider identity, runtime/frontend application revision, health journeys,
and the remote `/chat` journey. A staging candidate or unfinalized result is not production proof.

### 3. Read-only production capture and preflight

Create a restricted, timestamped evidence directory. Capture bounded metadata only; do not manually
record `helm get values --all`, dump Secrets, or record response bodies. Schema-v2 finalization reads
the release's computed Helm values transiently and records only the bounded `helmStoredValues` pass
result after verifying the image repository, immutable tag, pull policy, and production isolation:

```bash
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
CAPTURE="operator-evidence/dspace-prod-reconciliation-$STAMP"
install -d -m 0700 "$CAPTURE"
helm --kubeconfig "$PROD_KUBECONFIG" -n dspace history dspace --max 10 -o json >"$CAPTURE/helm-history.json"
helm --kubeconfig "$PROD_KUBECONFIG" -n dspace status dspace -o json >"$CAPTURE/helm-status.json"
kubectl --kubeconfig "$PROD_KUBECONFIG" -n dspace get deployment dspace \
  -o jsonpath='{.metadata.uid}{"\n"}{.spec.template.spec.containers[?(@.name=="dspace")].image}{"\n"}' \
  >"$CAPTURE/deployment-identity.txt"
kubectl --kubeconfig "$PROD_KUBECONFIG" -n dspace get pods \
  -l app.kubernetes.io/name=dspace,app.kubernetes.io/instance=dspace \
  -o 'custom-columns=NAME:.metadata.name,UID:.metadata.uid,START:.status.startTime,IMAGE_ID:.status.containerStatuses[?(@.name=="dspace")].imageID' \
  >"$CAPTURE/pods.txt"
PROD_HOST=$(python3 scripts/app_chart.py resolve-host \
  --values docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.prod.yaml)
PUBLIC_BUILD=$(mktemp)
DIRECT_BUILD=$(mktemp)
trap 'rm -f "$RECOVERY_CONFIG" "$PUBLIC_BUILD" "$DIRECT_BUILD"' EXIT
curl --fail --silent --show-error --max-time 10 --max-filesize 16384 \
  "https://$PROD_HOST/build-meta.json" >"$PUBLIC_BUILD"
jq -e '{gitSha, generatedAt, source}' "$PUBLIC_BUILD" \
  >"$CAPTURE/public-build-identity.json"
POD=$(kubectl --kubeconfig "$PROD_KUBECONFIG" -n dspace get pods \
  -l app.kubernetes.io/name=dspace,app.kubernetes.io/instance=dspace \
  -o jsonpath='{.items[0].metadata.name}')
HTTP_PORT=$(kubectl --kubeconfig "$PROD_KUBECONFIG" -n dspace get deployment dspace -o json \
  | jq -er '[.spec.template.spec.containers[] | select(.name == "dspace")
    | .ports[] | select(.name == "http") | .containerPort] | if length == 1 then .[0] else error("expected one http port") end')
timeout 10s kubectl --kubeconfig "$PROD_KUBECONFIG" get --raw \
  "/api/v1/namespaces/dspace/pods/$POD:$HTTP_PORT/proxy/build-meta.json" \
  | head -c 16384 >"$DIRECT_BUILD"
jq -e '{gitSha, generatedAt, source}' "$DIRECT_BUILD" \
  >"$CAPTURE/direct-build-identity.json"
```

Do not run `dspace-release-verify` against the pre-change 3.0.2 deployment: the full verifier
correctly rejects the currently installed chart 3.0.2 when validating the new target. The bounded
captures above retain only the
three allowlisted identity fields and cap each response at 16 KiB. Before evidence reservation or
mutation, run the existing recipe's exact read-only digest-qualified render and structural
validation sequence:

```bash
eval "$(python3 scripts/app_config.py shell --app dspace --env prod \
  --config docs/examples/apps/dspace.env --tag main-1a31a56 --require-tag)"
CHART_VERSION=$(sed -e 's/#.*$//' -e '/^[[:space:]]*$/d' \
  "$SUGARKUBE_VERSION_FILE" | head -n1)
test "$CHART_VERSION" = 3.0.3
CHART_COORDINATE=$(python3 scripts/dspace_release_manifest.py preflight \
  --manifest deployment-candidates/dspace/recovery-prod.json --environment prod \
  --image-tag "$SUGARKUBE_TAG" --chart-version "$CHART_VERSION" \
  --chart-ref "$SUGARKUBE_CHART" --print-chart-coordinate)
test "$CHART_COORDINATE" = \
  'oci://ghcr.io/democratizedspace/charts/dspace@sha256:6ee663c426673bc0e516ed8f8b0ab11a918d2f2bb81fc9047b3eb37b78329f5c'
PROD_HOST=$(python3 scripts/app_chart.py resolve-host --values "$SUGARKUBE_VALUES")
python3 scripts/app_chart.py preflight \
  --app "$SUGARKUBE_APP" --env "$SUGARKUBE_ENV" --tag "$SUGARKUBE_TAG" \
  --chart "$CHART_COORDINATE" --version "${SUGARKUBE_VERSION:-}" \
  --version-file "$SUGARKUBE_VERSION_FILE" --values "$SUGARKUBE_VALUES" \
  --release "$SUGARKUBE_RELEASE" --namespace "$SUGARKUBE_NAMESPACE" \
  --host "$PROD_HOST" --pull-policy Always
```

This must prove chart 3.0.3 at the approved OCI digest and the immutable application image while
rejecting staging metrics, the staging metrics Secret reference, ServiceMonitor leakage, or literal
Secret material. Review that the resolved values chain is exactly the dev base plus production
overlay. Legitimate production `secretKeyRef`/`existingSecret` names are allowed, but never print
their values. Stop on any render, OCI revision, digest, provider, cluster identity, or staging-gate
mismatch.

### 4. Guarded production mutation and verification

Only after the approved window and read-only review, invoke the guarded promotion recipe—not raw
`helm upgrade`, `helm rollback`, or `kubectl apply`:

```bash
just app-promote-prod app=dspace tag=main-1a31a56 \
  manifest=deployment-candidates/dspace/recovery-prod.json \
  staging_evidence="$STAGING_EVIDENCE" smoke_runner="$DSPACE_SMOKE_RUNNER" \
  staging_config="$RECOVERY_CONFIG" staging_kubeconfig="$STAGING_KUBECONFIG" \
  kubeconfig="$PROD_KUBECONFIG"
PROD_EVIDENCE=$(python3 scripts/dspace_release_manifest.py evidence-path \
  --manifest deployment-candidates/dspace/recovery-prod.json)
python3 scripts/dspace_release_manifest.py validate --final --manifest "$PROD_EVIDENCE"
```

Review the finalized record together with fresh bounded Helm status/history and Deployment/pod
capture. All serving pods and Helm stored image values must use `main-1a31a56` and the approved
image digest; installed chart version and OCI provenance must be 3.0.3 and its chart revision/digest.
Application, runtime, and frontend identity must remain the application revision, not the chart
revision. Public and direct identity, replica agreement, health paths, configuration/provider, and
`/chat` must all pass. Preserve candidate, finalized records, command exit statuses, timestamps, and
secret-safe captures in the external maintenance record.

Lift the Helm freeze only after finalized **production** evidence exists, validation succeeds, every
verification result is true, the staging gate matches both revisions and every immutable coordinate,
and reviewers accept the bounded pre/post capture. Otherwise the freeze remains.

### 5. Failure reconciliation and immutable recovery

There is deliberately no fabricated finalized record for the inconsistent pre-change revision 8,
so it is not a valid rollback target. On any failure, stop, keep the freeze, preserve the reservation
or redacted failure evidence and bounded post-failure status, and do not immediately mutate again.
Never use `helm rollback <revision>`, `--reuse-values`, `v3.0.1`, mutable coordinates, or staging
evidence as a production target.

For this first reconciliation, the truthful recovery path is a separately approved retry/reconcile
to the same immutable production candidate, using the complete Git-controlled production values and
the guarded `app-promote-prod` sequence above after diagnosing the failed invocation. If a different
state must be restored, first supply a genuine finalized production manifest for that immutable
target and use `just dspace-manifest-rollback` with its explicit
`dspace:prod:<40-character-application-SHA>` confirmation, production kubeconfig, complete production
values, executable verifier and `/chat` runner, and a new bounded evidence path. Without such a
finalized production target, recovery is blocked rather than guessed. A successful retry still
requires complete post-mutation finalization before the freeze can be reconsidered.

## Mandatory release verification

DSPACE staging and production releases are verified against an approved immutable release
manifest. By default, the verifier uses the strict `build-info-v1` contract: public and direct
`/build-info.json`, exact public and direct HTML revision markers, and agreement across replicas.
It derives the proxy port from the unique `http` port on the unique Deployment `dspace` container
and requires every pod's unique `dspace` container to declare that same valid port. It then invokes
DSPACE's non-destructive remote `/chat` harness with an explicit `--identity-contract
build-info-v1`. It uses read-only Kubernetes API pod proxies. Successful
bounded results are included in finalized evidence as `runtimeVerification`; response bodies,
child output, browser artifacts, headers, cookies, credentials, and request payloads are not saved.

The sole exception is the complete coordinate tuple in
`docs/apps/dspace.prod-recovery-coordinates.json`, augmented by candidate provider `openai`: schema
2, application `3.0.1`, source revision `1a31a569aff2dbeb238e8c2688b9e85140d2077d`, chart source
revision `62da11005354e9f9a89c2e58584cdce4c8ec35aa`, image tag `main-1a31a56`, image digest
`sha256:23dbc573377549136c1f10b05706b3c176ffbabaf04a3194381a24752104a401`, chart `3.0.3` with digest
`sha256:6ee663c426673bc0e516ed8f8b0ab11a918d2f2bb81fc9047b3eb37b78329f5c`, and semantic tag
`v3.0.1`. Only that exact candidate uses `legacy-build-meta-v1`. The verifier proves identical
`gitSha`, valid non-empty `generatedAt`, and non-empty `source` through public and every direct
`/build-meta.json`, while still validating bounded non-empty root documents, and passes the legacy
contract explicitly to the smoke runner. This is not a fallback: any coordinate drift uses the
modern contract and a modern identity failure remains fatal. The exception changes neither the
immutable recovery coordinates nor candidate approval.

The separately reviewed production metrics target selects chart 3.0.3 at source revision
`62da11005354e9f9a89c2e58584cdce4c8ec35aa` and digest
`sha256:6ee663c426673bc0e516ed8f8b0ab11a918d2f2bb81fc9047b3eb37b78329f5c` while retaining every
3.0.1 application coordinate above. That exact tuple is also eligible for the same bounded legacy
identity contract; this is not a general version fallback.

The exact immutable DSPACE 3.1.0 artifact (source `018687f5a7f4de45508c6e36eb28afb3e44da24d`,
image `main-018687f`, and chart `3.1.1`) also predates `build-info-v1` and is explicitly allowlisted
for the same strict legacy contract. This is not a general fallback: every coordinate must match,
and unrecognized or future releases remain subject to the modern identity contract.

Use the [containerized DSPACE smoke runner](https://github.com/democratizedspace/dspace/blob/main/docs/qa/container-chat-smoke.md),
merged in DSPACE #4882 and updated by #4889 to Node **24.22.3**. The adapter requires an existing
host Node 24.22.3 or newer Node 24 patch and a Linux Docker daemon with native amd64 or arm64
execution. Do not install host browser/npm dependencies during release verification; stop if the
runner environment is unavailable. Build and offline-check the dedicated image from clean reviewed
runner source as documented upstream, separately from any live release operation.

The image and adapter checkout must have the same full reviewed runner SHA. The adapter resolves
the local image to an immutable image ID without pulling. Record both runner coordinates separately
from the candidate application SHA/image/chart digests. The image pins Playwright 1.54.2 and Node
24.22.3; CI test discovery, offline Chromium launch and its negative control are tooling evidence,
not staging journeys, live inference or proof of the deployed application's runtime.

For the modern v3.1.0 contract, configure the environment of the guarded verifier explicitly:

```bash
export DSPACE_SMOKE_RUNNER=/reviewed/dspace/scripts/run-container-chat-smoke.mjs
export DSPACE_SMOKE_IMAGE='dspace-chat-smoke:<reviewed-full-runner-SHA>'
export DSPACE_EXPECTED_PROVIDER_CONFIG_CONTRACT=chat-default-provider-v1
export DSPACE_SMOKE_TIMEOUT_MS=240000
STAGING_KUBECONFIG="$HOME/.kube/config-sugarkube-staging"
PROD_KUBECONFIG="$HOME/.kube/config-sugarkube-prod"
test -x "$DSPACE_SMOKE_RUNNER"

just dspace-release-verify \
  env=staging \
  manifest=deployment-evidence/dspace/staging/<finalized-record>.json \
  smoke_runner="$DSPACE_SMOKE_RUNNER" \
  kubeconfig="$STAGING_KUBECONFIG"

just dspace-release-verify \
  env=prod \
  manifest=deployment-candidates/dspace/prod.json \
  smoke_runner="$DSPACE_SMOKE_RUNNER" \
  kubeconfig="$PROD_KUBECONFIG"
```

Add `config=<nondefault-environment-config>` when verification must use a
nondefault app config.

The provider-config environment value is necessary because the current modern verifier argv
omits `--provider-config-contract`. Historical/hotfix contracts must retain their exact explicit
flags; do not reinterpret them as modern. The adapter's 240-second budget plus 10-second cleanup
allowance fits the verifier's 300-second timeout. Never weaken completion or identity checks to
compensate for a missing browser, timeout or absent runtime.

For standalone completion JSON, use `--runner-revision` for the reviewed runner SHA, not the target
application SHA, and an unshared fresh result path in an existing directory. The adapter clears
existing results before preflight and accepts only fresh matching completion proof; exit zero
without proof is failure. Keep that result, runner image ID/revision and exit status beside target
evidence. Guarded Sugarkube finalization instead records bounded `runtimeVerification`; the JSON
alone does not create finalized evidence or authorize promotion. Intercepted transport sends no
live provider requests, so live relay E2EE, metrics, monitoring and soak checks remain required.

Deploy staging from its approved candidate; finalized evidence is created only after post-rollout
verification succeeds:

```bash
just app-deploy app=dspace env=staging tag=main-REPLACE_SHORTSHA \
  manifest=deployment-candidates/dspace/staging.json \
  smoke_runner="$DSPACE_SMOKE_RUNNER" \
  kubeconfig="$STAGING_KUBECONFIG"
```

Production promotion additionally requires finalized staging evidence. Before production render,
reservation, or mutation, Sugarkube compares immutable coordinates, checks the recorded staging
Helm revision remains live, reruns complete staging verification, and separately requires an exact
authorization bound to the production candidate's full source revision:

```bash
just app-promote-prod \
  app=dspace \
  tag=main-REPLACE_SHORTSHA \
  manifest=deployment-candidates/dspace/prod.json \
  staging_evidence=deployment-evidence/dspace/staging/<finalized-record>.json \
  smoke_runner="$DSPACE_SMOKE_RUNNER" \
  kubeconfig="$PROD_KUBECONFIG" \
  staging_kubeconfig="$STAGING_KUBECONFIG" \
  confirm="dspace:prod:<40-character-application-SHA>"
```

If staging used a nondefault app config, pass that distinct path as
`staging_config=<staging-config>` during promotion. Do not pass the production
`config=` value as `staging_config=`.

Final records are written below `deployment-evidence/dspace/<environment>/`, unless `evidence=` is
explicit. A post-mutation failure exits nonzero, preserves the reservation for reconciliation, and
does not finalize success, retry, downgrade, or roll back. For a `token-place` default, origin and
model expectations come from the ordered values chain. For `openai`, those arguments are omitted;
OpenAI remains discoverable and missing-key gated without a real key. Standalone production
verification uses the same command with `env=prod` and a production candidate or final record.

### Exact v3.0.2 hotfix identity contract

The hotfix at source `47900748f61e1ef38c6289fc697f7a070f7fa3c9` uses the full tag
`hotfix-47900748f61e1ef38c6289fc697f7a070f7fa3c9` and image index
`sha256:5d16cde03df4cfe9a52341c26bb6167234d315f896d422af38383b760bebcfe0`.
Only the complete hotfix/chart/provider tuples in `HOTFIX_IDENTITY_COORDINATES` select
`hotfix-build-meta-oci-v1` and `hotfix-openai-config-v1`. All existing image, chart,
environment, readiness, rollback, and finalization checks remain required.

This contract requires the companion DSPACE runner. It validates a digest-bound OCI
index and both platform configs, extracts application version `3.0.2` from the immutable
version label `v3.0.2+4790074`, verifies the full runtime source revision, and proves the
OpenAI default through the isolated browser submission journey. It does not treat a
runtime environment variable or a caller-supplied manifest version as artifact proof.
Sugarkube requires the runner's successful `DSPACE_ARTIFACT_VERSION_PROOF` result and
rejects missing, duplicate, or mismatched proof. Every direct pod and the public health
endpoint must also agree with `v3.0.2+4790074`; this is a separate configuration check.

The offline cross-repository regression executes the real runner's argument and contract
validators. Run it with `DSPACE_RUNNER_CHECKOUT` pointing to the pinned companion checkout:

```bash
DSPACE_RUNNER_CHECKOUT=/path/to/dspace pytest -q tests/test_dspace_hotfix_runner_integration.py
```

Chart 3.1.3 adds the explicit runtime-version override required by this hotfix.
Its published source is `2d2c4c7d384d5da270a94654a87c71a5bdfd0420`, and its OCI digest is
`sha256:ee1a6bcdd5f601d473e81ea42c8dfb4055fa0016e7c4fd5fcd163ef3dba7a366`.
The archive digest is
`sha256:a510404755d093f9698549f8af1b5d1869bc404ab0fb47e58af956307d95f4b4`.
[Publication run 42975610091](https://github.com/democratizedspace/dspace/actions/runs/42975610091)
verified the packaged provenance and published OCI coordinate. The chart's `appVersion`
and default image remain 3.1.0; they do not select the application for this hotfix.

Use `config=docs/examples/apps/dspace-hotfix-302.env` for bounded staging verification
of the final dated candidate, not as production approval. It selects chart 3.1.3
and appends `runtimeVersion: v3.0.2+bfb9102` and `chat.defaultProvider: openai`.
The exact source is `bfb910201e23119cb26902d8ca6787070150b695`, with index
`sha256:e9331b4319a9d475b910be6265613202a93d133fe33a8c6685dd962746a8e485`
and arm64 manifest
`sha256:32fc5c8ccc31ac57d9f915527a22ed82143f44ae2752a25b441c87372d7228ce`.
All historical image/chart tuples remain supported with their matching runtime
labels; preserve their finalized evidence and rollback configuration.

[Publication run 43777310401](https://github.com/democratizedspace/dspace/actions/runs/43777310401)
pushed this immutable image but failed its post-push registry token read. Its
original receipt records `published: true`, `verified: false`, and no completed
smokes. Do not rerun the publisher. The companion authenticates the original OCI
index/platform/config bytes and both source/version labels; that metadata proof
is not runtime acceptance.

The integration workflow pins actual [DSPACE PR #4879](https://github.com/democratizedspace/dspace/pull/4879)
head `ee6695a1eb140a01c7588017c290cec2e4b7f22e`, tree
`f8f380061263ade633aa94642d7753ff261c92ff`, not a speculative merge SHA.
Its 136 focused local contract tests passed. Check that PR's final-head CI and
reviews before readiness; if its head changes, recheck the tree, refresh the pin
and rerun the integration. The existing integration exercises all four supported
image/chart tuples against the real pinned companion.

Use a fresh candidate/evidence packet and the existing bounded staging
runtime/health verification, reusing earlier broad functional acceptance. No new
recovery workflow or broad qualification campaign is required. The date is
November 15 in the candidate changelog; a successful metadata check does not
establish a production release. Owner approval and production rollback evidence
remain separate gates. Supply the exact image tag and candidate manifest through
the existing release workflow. This config intentionally has no production
values chain; shared chart pins and staging/production defaults are unchanged.

The old chart 3.0.3 compatibility tuple remains supported for historical evidence;
its source render cannot supply the required hotfix health version. No compatibility
tuple grants rollout authority or replaces successful staging verification before production.

## Artifact model

- App repository responsibilities: build `ghcr.io/democratizedspace/dspace`, publish immutable image tags, maintain the Helm chart, and publish immutable chart versions to `oci://ghcr.io/democratizedspace/charts/dspace`.
- Sugarkube responsibilities: select `dev`, `staging`, or `prod`; load `docs/examples/apps/dspace.env` or a local override; select kubeconfig/context; install or upgrade Helm; verify rollout status, logs, and public paths.
- Cloudflare responsibilities: DNS and Tunnel routes to Traefik are outside Helm and must exist before public verification.

| Coordinate         | Value                                                                                                                                                                                                                                     |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Image              | `ghcr.io/democratizedspace/dspace`                                                                                                                                                                                                        |
| Chart              | `oci://ghcr.io/democratizedspace/charts/dspace`                                                                                                                                                                                           |
| Release            | `dspace`                                                                                                                                                                                                                                  |
| Namespace          | `dspace`                                                                                                                                                                                                                                  |
| App config         | `docs/examples/apps/dspace.env`                                                                                                                                                                                                           |
| Chart version pins | Shared/default `docs/apps/dspace.version`; historical staging target `docs/apps/dspace.staging.version` (`3.1.2` for application `3.1.1`); production `docs/apps/dspace.prod.version` (`3.0.3`, chart-only application 3.0.1 maintenance) |
| Production tag pin | `docs/apps/dspace.prod.tag`                                                                                                                                                                                                               |
| Verify paths       | `/config.json`, `/healthz`, `/livez`                                                                                                                                                                                                      |

### Approved chart 3.0.3 publication provenance

Chart `3.0.3` was published from chart source revision
`62da11005354e9f9a89c2e58584cdce4c8ec35aa` by upstream PR
`democratizedspace/dspace#4816` and tag `chart-v3.0.3`. Publication workflow
[run 31632262039, attempt 2](https://github.com/democratizedspace/dspace/actions/runs/31632262039)
completed successfully in job `94238380995`. The OCI manifest digest is
`sha256:6ee663c426673bc0e516ed8f8b0ab11a918d2f2bb81fc9047b3eb37b78329f5c`; the independently
verified packaged archive SHA-256 is
`2b6528eefd487be8a52db8ea44f118310351976ee32b29fb6115c8081916280a`. The archive hash is
publication provenance only and is intentionally not added to the release-manifest schema.

### Artifact links

Use these links before changing a deployment so the workflow runs, package versions, and source paths all agree.

| Artifact                   | Link                                                                                                                                                                                                                                |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| App repository             | [DSPACE app repository](https://github.com/democratizedspace/dspace)                                                                                                                                                                |
| Image workflow             | [Recent image workflow runs](https://github.com/democratizedspace/dspace/actions/workflows/ci-image.yml)                                                                                                                            |
| Successful main image runs | [Successful main image workflow runs](https://github.com/democratizedspace/dspace/actions/workflows/ci-image.yml?query=branch%3Amain+is%3Asuccess)                                                                                  |
| Successful v3 image runs   | [Successful v3 image workflow runs](https://github.com/democratizedspace/dspace/actions/workflows/ci-image.yml?query=branch%3Av3+is%3Asuccess)                                                                                      |
| GHCR image package         | [GHCR image package versions](https://github.com/democratizedspace/dspace/pkgs/container/dspace)                                                                                                                                    |
| Chart workflow             | [Recent chart workflow runs](https://github.com/democratizedspace/dspace/actions/workflows/ci-helm.yml)                                                                                                                             |
| GHCR chart package         | No public package page is associated yet; use the [DSPACE chart package lookup](https://github.com/orgs/democratizedspace/packages?repo_name=dspace&q=charts%2Fdspace) and `helm show chart` below until the chart package appears. |
| Dockerfile                 | [Application Dockerfile](https://github.com/democratizedspace/dspace/blob/main/Dockerfile)                                                                                                                                          |
| Chart source               | [Helm chart source](https://github.com/democratizedspace/dspace/tree/main/charts/dspace)                                                                                                                                            |
| App release guide          | [Sugarkube release guide in the app repo](https://github.com/democratizedspace/dspace/blob/main/docs/ops/sugarkube-release.md)                                                                                                      |

## Environment topology

- `env=dev`: future single-node/non-HA environment using `docs/examples/dspace.values.dev.yaml`.
  The dev overlay intentionally does not choose a token.place origin; developers who need local runtime routing can copy `docs/examples/apps/dspace.env` to a local app config and add chart-supported `env` entries to their private values file.
- `env=staging`: HA staging on the staging Sugarkube cluster with host `staging.democratized.space` and values `docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml`.
  The historical repository pin and August 17 evidence record describe DSPACE application `3.1.1` release at chart `3.1.2` and Helm revision 30. The staging values inject `DSPACE_TOKEN_PLACE_URL=https://staging.token.place` and `DSPACE_TOKEN_PLACE_CHAT_MODEL=qwen3-8b-instruct` and persist the authenticated metrics ServiceMonitor configuration discovered by kube-prometheus-stack. That recorded release used immutable image `main-22f506e` from source `22f506e07e0b5abfd0cf756e9c5827c0458fb4b2`, with finalized evidence recorded at `deployment-evidence/dspace/staging/main-22f506e-20260817T094911Z.json`. The metrics bearer value is not committed; operators manage the existing `dspace-staging-metrics-token` Secret out of band.
- `env=prod`: HA production on the production Sugarkube cluster with host `democratized.space` and values `docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.prod.yaml`.
  The production overlay injects `DSPACE_TOKEN_PLACE_URL=https://token.place` and `DSPACE_TOKEN_PLACE_CHAT_MODEL=llama-3.1-8b-instruct`. The historical approved production target is recovery chart `3.0.3` and image `ghcr.io/democratizedspace/dspace:main-1a31a56`; the earlier baseline recorded chart `3.0.2`. Neither a source pin nor that historical baseline establishes current live state. The production values enable authenticated metrics and the ServiceMonitor contract.
- Optional legacy/canary host `prod.democratized.space` uses `docs/examples/dspace.values.prod-subdomain.yaml`. The `dspace-oci-deploy-prod-subdomain` compatibility command selects the secret-free `docs/examples/apps/dspace-prod-subdomain.env` config, preserving that overlay while routing through the same manifest validation, OCI preflight, Helm deployment, and evidence finalization as the generic production path.

## Find or publish GHCR image

Find the successful image workflow in the DSPACE app repo and copy its lowercase branch-SHA tag. Semantic tags are distribution aliases, not staging or production coordinates. The GitHub Actions workflow page is where recent builds are found; the GHCR package page is where published image tags are cross-checked. Do not deploy `latest`, a bare branch name, or an environment name.

Web UI shortcuts:

- Open [recent image workflow runs](https://github.com/democratizedspace/dspace/actions/workflows/ci-image.yml), [successful main image runs](https://github.com/democratizedspace/dspace/actions/workflows/ci-image.yml?query=branch%3Amain+is%3Asuccess), or [successful v3 image runs](https://github.com/democratizedspace/dspace/actions/workflows/ci-image.yml?query=branch%3Av3+is%3Asuccess).
  Consult `v3` in addition to `main` because the Raspberry Pi bootstrap helper still defaults `DSPACE_BRANCH` to `v3` for current DSPACE clones.
- Open [GHCR image package versions](https://github.com/democratizedspace/dspace/pkgs/container/dspace).
- Copy the immutable tag from a successful workflow summary or package version.

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
gh run list --repo democratizedspace/dspace --workflow ci-image.yml --branch main --status success --limit 5
```

If no suitable image exists, obtain separate publication authorization before running the app image workflow, then return here with evidence of a fully successful run and its immutable tag. Do not rerun a failed image publication that already occupied its branch-SHA coordinate; fix through a new reviewed source commit.

```bash
gh workflow run ci-image.yml --repo democratizedspace/dspace --ref main
```

## Confirm/publish OCI chart

Sugarkube deploys the chart version resolved from `docs/examples/apps/dspace.env`: `SUGARKUBE_VERSION_FILE_<ENV>` for the requested environment when present, otherwise the shared `docs/apps/dspace.version` fallback. Use [recent chart workflow runs](https://github.com/democratizedspace/dspace/actions/workflows/ci-helm.yml) to find chart publish attempts, `helm show chart` below to confirm available immutable chart versions, and [the chart source](https://github.com/democratizedspace/dspace/tree/main/charts/dspace) to review the chart content that should match the pinned version. The DSPACE OCI chart does not currently have an associated public GHCR package page; check the [DSPACE chart package lookup](https://github.com/orgs/democratizedspace/packages?repo_name=dspace&q=charts%2Fdspace) until that package page appears.

```bash
STAGING_CHART_PIN=$(python3 scripts/app_config.py json --app dspace --env staging | jq -r .SUGARKUBE_VERSION_FILE)
STAGING_CHART_VERSION=$(sed -e 's/#.*$//' -e '/^[[:space:]]*$/d' "$STAGING_CHART_PIN" | head -n 1)
```

```bash
helm show chart oci://ghcr.io/democratizedspace/charts/dspace --version "$STAGING_CHART_VERSION"

PROD_CHART_PIN=$(python3 scripts/app_config.py json --app dspace --env prod | jq -r .SUGARKUBE_VERSION_FILE)
PROD_CHART_VERSION=$(sed -e 's/#.*$//' -e '/^[[:space:]]*$/d' "$PROD_CHART_PIN" | head -n 1)
helm show chart oci://ghcr.io/democratizedspace/charts/dspace --version "$PROD_CHART_VERSION"
```

If the chart changed, prepare an unused chart version in DSPACE, review it, and obtain separate
publication authorization. The [chart workflow source](https://github.com/democratizedspace/dspace/blob/main/.github/workflows/ci-helm.yml)
accepts only a push of exactly `chart-v<Chart.yaml version>` at the reviewed immutable source
commit. It has no manual dispatch trigger. Branch pushes and `gh workflow run ci-helm.yml` do not
publish charts. Existing coordinates cannot be replaced; chart `3.0.1` is tombstoned. Preserve
both authoritative-absence checks and the successful run's source SHA, package hash and OCI digest.
The application Git tag `v<applicationVersion>` is separate from the chart tag; the published
GitHub application release event produces the semantic image alias and combined release manifest
only after the immutable image and chart prerequisites exist. A Git tag push alone does not
publish that semantic image alias.

After verifying the published chart, copy its exact version from the reviewed successful
publication evidence into `CHART_VERSION`, replacing the placeholder below. Do not reuse the
historical recovery shell's variable or the currently pinned staging/production versions; those
may select a different chart. Then update the selected local Sugarkube pin for review:

```bash
CHART_VERSION='REPLACE_WITH_REVIEWED_PUBLISHED_CHART_VERSION'
just app-chart-bump app=dspace version="$CHART_VERSION" env=staging
```

`app-chart-bump` checks the existing OCI chart with `helm show chart` and writes the resolved local
version file. It neither publishes the chart nor deploys it. Review and commit the pin separately;
production pin changes require production approval after staging sign-off. The guarded deployment
uses the approved manifest's immutable chart digest, not a fresh mutable tag resolution.

## Deploy staging

### Release-manifest approval and evidence flow

After the upstream publication prerequisites and release-owner decisions are satisfied,
download the `dspace-release-manifest` artifact from the successful upstream semantic-release
job in the image workflow and extract `dspace-release-manifest/dspace-release-manifest.json`.
Do not copy coordinates from mutable package tags. Create a canonical staging
candidate with an explicit UTC approval time, approver identity, and one of the
configuration contract's exact provider values (`token-place` or `openai`). For the current
v3.1.0 candidate use `token-place`. Set `STAGING_APPROVED_AT` and `STAGING_APPROVED_BY` from
the actual staging approval record; use separate `PROD_APPROVED_AT` and `PROD_APPROVED_BY`
values from the later production approval. Never copy an example timestamp as approval:

```bash
python3 scripts/dspace_release_manifest.py candidate \
  --upstream dspace-release-manifest/dspace-release-manifest.json \
  --output deployment-candidates/dspace/staging.json \
  --environment staging --provider token-place \
  --approved-at "$STAGING_APPROVED_AT" --approved-by "$STAGING_APPROVED_BY"
python3 scripts/dspace_release_manifest.py validate \
  --manifest deployment-candidates/dspace/staging.json
```

Inspect and review that file before approval. Deploying performs a read-only OCI
preflight first. It uses the OCI Distribution API through `oras`, not GitHub's
Packages REST API, and does not need an ad hoc `read:packages` token for public
artifacts. If a package is private, use the registry's normal OCI login flow;
never put credentials in a manifest or command argument. The OCI-native manual
fallback is:

```bash
oras manifest fetch --descriptor \
  ghcr.io/democratizedspace/dspace:"$APP_TAG"
IMAGE_DIGEST=$(oras manifest fetch --descriptor ghcr.io/democratizedspace/dspace:"$APP_TAG" | jq -r .digest)
oras manifest fetch ghcr.io/democratizedspace/dspace@"$IMAGE_DIGEST"
# Fetch each index manifest and its config blob by digest; inspect every config label.
oras manifest fetch --descriptor \
  ghcr.io/democratizedspace/charts/dspace:"$CHART_VERSION"
CHART_DIGEST=$(oras manifest fetch --descriptor ghcr.io/democratizedspace/charts/dspace:"$CHART_VERSION" | jq -r .digest)
oras manifest fetch ghcr.io/democratizedspace/charts/dspace@"$CHART_DIGEST"
# Fetch the chart config blob by digest and inspect its revision annotation.
```

Pass the candidate to staging and preserve the generated final record:

```bash
just app-deploy app=dspace env=staging tag="$APP_TAG" \
  manifest=deployment-candidates/dspace/staging.json \
  smoke_runner="$DSPACE_SMOKE_RUNNER" \
  kubeconfig="$STAGING_KUBECONFIG"
EVIDENCE=$(python3 scripts/dspace_release_manifest.py evidence-path \
  --manifest deployment-candidates/dspace/staging.json)
git add "$EVIDENCE"
# Commit it after review, or attach that exact file to the external promotion record.
```

The approved `chartVersion` remains the human-readable pin and the Helm metadata
checked after rollout. The guarded deploy itself passes Helm the immutable
`oci://ghcr.io/democratizedspace/charts/dspace@<chartDigest>` coordinate emitted
by the successful preflight, without `--version`, so a tag cannot be resolved
again between approval and installation.
The mutation also carries an opaque description derived from the evidence
reservation. Finalization requires that description and the Helm revision to
remain stable across runtime evidence collection, failing closed if another
upgrade or rollback becomes current.
Finalization also waits for a bounded period for old release pods undergoing
graceful rollout termination to disappear. It never filters out a still-running
release pod: every remaining pod must satisfy the approved image and readiness
checks.

After staging sign-off, generate a separate `prod` candidate from the **same
upstream manifest**, approve it independently, and promote it. The image tag,
image digest, chart version, chart digest, and full source SHA must remain the
same; `semanticTag` must equal `v<applicationVersion>` and is only corroborating evidence.

```bash
python3 scripts/dspace_release_manifest.py candidate \
  --upstream dspace-release-manifest/dspace-release-manifest.json \
  --output deployment-candidates/dspace/prod.json \
  --environment prod --provider token-place \
  --approved-at "$PROD_APPROVED_AT" --approved-by "$PROD_APPROVED_BY"
TARGET_SHA=$(jq -er '.sourceRevision' deployment-candidates/dspace/prod.json)
just app-promote-prod app=dspace tag="$APP_TAG" \
  manifest=deployment-candidates/dspace/prod.json \
  staging_evidence=deployment-evidence/dspace/staging/<finalized-record>.json \
  smoke_runner="$DSPACE_SMOKE_RUNNER" \
  kubeconfig="$PROD_KUBECONFIG" \
  staging_kubeconfig="$STAGING_KUBECONFIG" \
  confirm="dspace:prod:${TARGET_SHA}"
EVIDENCE=$(python3 scripts/dspace_release_manifest.py evidence-path \
  --manifest deployment-candidates/dspace/prod.json)
git add "$EVIDENCE"
```

The finalized JSON is sufficient to reconstruct the release using the recorded
branch-SHA image tag and digest plus chart version and the exact digest-qualified
chart deployment coordinate, without resolving
`latest`, a branch, an environment tag, or the semantic tag.
`runtimeSourceRevisionMethod` remains `podImageID+ociRevisionAnnotation` as the
persisted source-provenance method: every pod image ID must equal the approved
digest and that exact OCI artifact's revision annotation must equal the full
approved SHA. Current verification additionally checks public and direct
`/build-info.json`, frontend revision markers, agreement across serving replicas,
provider expectations, and the non-destructive `/chat` journey. Finalization also
reasserts the connected cluster environment,
requires Helm to report the selected release and namespace as deployed with the
exact approved DSPACE chart version, and accepts only Running, Ready pods owned
through the selected Helm release's Deployment and ReplicaSet. Each DSPACE
container must use the approved repository and immutable image tag before its
resolved image ID is accepted.

Immediately before Helm changes the release, the guarded recipe atomically creates
`<evidence-path>.reservation`. This sidecar binds the normalized destination,
approved-candidate fingerprint, environment, Helm release, and namespace to one
opaque invocation identifier. A competitor stops before Helm or Kubernetes
mutation. Only the owner can finalize; success atomically creates the JSON and
removes the sidecar.

Failures after reservation deliberately leave the sidecar. There is no timeout or
automatic stale-lock takeover. For recovery, first inspect and reconcile the
selected cluster, Helm release, pods, intended candidate, and existing evidence. If
that proves the original invocation cannot resume and its destination must be
abandoned, explicitly remove that exact sidecar (for example,
`rm -- deployment-evidence/dspace/staging/<file>.json.reservation`) and rerun the
guarded command. Never remove a reservation merely because it is old.

Only after separate operator approval, deploy the approved immutable, environment-neutral DSPACE image with runtime `/config.json` support. The image tag stays the same as it moves between staging and production; the Sugarkube values overlays, not image names, select the token.place origin.

Preferred generic command:

```bash
just app-deploy app=dspace env=staging tag="$APP_TAG" \
  manifest=deployment-candidates/dspace/staging.json \
  smoke_runner="$DSPACE_SMOKE_RUNNER" kubeconfig="$STAGING_KUBECONFIG"
```

Compatibility shim while migration is in progress:

```bash
just dspace-oci-deploy env=staging tag="$APP_TAG" \
  manifest=deployment-candidates/dspace/staging.json \
  smoke_runner="$DSPACE_SMOKE_RUNNER" kubeconfig="$STAGING_KUBECONFIG"
```

## Verify staging

Generic verification discovers the host from Helm values or Ingress, executes the configured DSPACE paths, prints a per-path body preview, and exits non-zero if any HTTP check fails. It does not validate the `/config.json` body, so staging sign-off also requires the explicit `curl | jq` routing gate below. Use `print_only=1` when you only want the curl commands for docs or troubleshooting.

```bash
just app-status app=dspace env=staging
```

```bash
just app-verify app=dspace env=staging
```

```bash
just app-verify app=dspace env=staging print_only=1
```

The runtime config check is a required routing gate, not an optional fallback: it must return the staging token.place origin before production promotion and before opening `/chat`. Browser Network must show staging DSPACE calling staging token.place; a staging request to production token.place is a stop-ship routing failure. If `/chat` fails after `/config.json` is correct, capture the browser CORS error plus the token.place response headers and escalate to the token.place operator; do not change DSPACE values to work around token.place CORS policy.

```bash
curl -fsS https://staging.democratized.space/config.json \
  | jq -e '
      .chat.defaultProvider == "token-place"
      and .tokenPlace.url == "https://staging.token.place"
      and .tokenPlace.model == "qwen3-8b-instruct"
    '
```

```bash
curl -fsS https://staging.democratized.space/healthz
```

```bash
curl -fsS https://staging.democratized.space/livez
```

## Cross-app token.place browser API release sequence

When a DSPACE release depends on browser calls to token.place API v1, keep the producer and consumer rollout ordered so Sugarkube verifies token.place behavior but never becomes the source of CORS response headers:

1. Under separate producer rollout authorization, verify or deploy the approved token.place image supporting API v1 relay E2EE and its browser CORS contract.
2. Run token.place public HTTP verification:

   ```bash
   just app-verify app=tokenplace env=staging
   ```

3. Run token.place browser CORS verification:

   ```bash
   just app-cors-verify app=tokenplace env=staging
   ```

4. Deploy DSPACE with the runtime origin settings from the current environment overlay.
5. Confirm DSPACE `/config.json` exposes the expected token.place runtime URL for the target environment.
6. Open `/chat`, send a message, and inspect Browser Network.

For the v3.1.0 default direct relay path, Browser Network must show, in order, `GET /api/v1/relay/servers/next`, `POST /api/v1/relay/requests`, and `POST /api/v1/relay/responses/retrieve` against `https://staging.token.place` in staging or
`https://token.place` in production. Confirm successful preflight and readable API-owned errors,
no `Authorization` header, no token.place credentials, and omitted fetch credentials. The request
payload contains ciphertext and safe routing metadata, never plaintext prompts, model, messages,
player state or secrets; `stream` is absent or false inside the encrypted request. Follow the
[v3.1 QA contract](https://github.com/democratizedspace/dspace/blob/main/docs/qa/v3.1.md)
for the separately gated optional proxy path and live evidence. The earlier plaintext browser
`/api/v1/chat/completions` example is superseded and must not be used for current release QA.

## Promote production

Promote only after staging QA, monitoring and soak sign-off, with separate operator approval. Prefer the generic command; it uses the reviewed prod values chain and environment chart pin. The existing chart `3.0.3` and `main-1a31a56` fallback are historical maintenance coordinates, not the current candidate. Pass the explicit approved immutable tag and manifest; first reconcile the pins and production model noted at the top of this page.

```bash
TARGET_SHA=$(jq -er '.sourceRevision' deployment-candidates/dspace/prod.json)
just app-promote-prod app=dspace tag="$APP_TAG" \
  manifest=deployment-candidates/dspace/prod.json \
  staging_evidence=deployment-evidence/dspace/staging/<finalized-record>.json \
  smoke_runner="$DSPACE_SMOKE_RUNNER" \
  kubeconfig="$PROD_KUBECONFIG" staging_kubeconfig="$STAGING_KUBECONFIG" \
  confirm="dspace:prod:${TARGET_SHA}"
```

Compatibility shim:

```bash
TARGET_SHA=$(jq -er '.sourceRevision' deployment-candidates/dspace/prod.json)
just dspace-oci-promote-prod tag="$APP_TAG" \
  manifest=deployment-candidates/dspace/prod.json \
  staging_evidence=deployment-evidence/dspace/staging/<finalized-record>.json \
  smoke_runner="$DSPACE_SMOKE_RUNNER" \
  kubeconfig="$PROD_KUBECONFIG" staging_kubeconfig="$STAGING_KUBECONFIG" \
  confirm="dspace:prod:${TARGET_SHA}"
```

## Verify production

```bash
just app-status app=dspace env=prod
```

```bash
just app-verify app=dspace env=prod
```

Print the generated curl commands without executing them when you need a manual fallback:

```bash
just app-verify app=dspace env=prod print_only=1
```

The runtime config check is a required production routing gate before opening `/chat`; browser Network should show production DSPACE calling production token.place. The immutable DSPACE image remains environment-neutral, and this production overlay selects the production token.place origin without rebuilding the image. If `/chat` fails after `/config.json` is correct, capture the browser CORS error plus the token.place response headers and escalate to the token.place operator; do not change DSPACE values to work around token.place CORS policy.

```bash
curl -fsS https://democratized.space/config.json \
  | jq -e '
      .chat.defaultProvider == "token-place"
      and .tokenPlace.url == "https://token.place"
      and .tokenPlace.model == "qwen3-8b-instruct"
    '
```

```bash
curl -fsS https://democratized.space/healthz
```

```bash
curl -fsS https://democratized.space/livez
```

## Rollback

Use the DSPACE-only manifest rollback command with a **previously finalized**
release-evidence record. The historical record supplies the chart digest,
chart version, immutable branch-SHA image tag, image digest, full source SHA,
application version, and approved provider. There are deliberately no separate
tag or chart-version arguments.

```bash
just dspace-manifest-rollback \
  env=staging \
  manifest=deployment-evidence/dspace/staging/previous-finalized-release.json \
  evidence=deployment-evidence/dspace/staging/rollback-20260727T120000Z.json \
  smoke_runner=/opt/dspace/bin/chat-smoke \
  verifier=/opt/dspace/bin/sugarkube-runtime-verifier
```

Production additionally requires a non-interactive confirmation bound to
DSPACE, `prod`, and the target record's full source revision. A generic `yes`
is rejected:

```bash
TARGET_SHA=REPLACE_WITH_THE_40_CHARACTER_TARGET_SOURCE_SHA
just dspace-manifest-rollback \
  env=prod \
  manifest=deployment-evidence/dspace/prod/previous-finalized-release.json \
  evidence=deployment-evidence/dspace/prod/rollback-20260727T120000Z.json \
  smoke_runner=/opt/dspace/bin/chat-smoke \
  verifier=/opt/dspace/bin/sugarkube-runtime-verifier \
  confirm="dspace:prod:${TARGET_SHA}"
```

Before reserving evidence or changing Helm/Kubernetes state, the command checks
cluster identity, validates the strict final manifest and fresh OCI provenance,
resolves the selected environment's complete current values chain, reads each
file once, records its repository-relative path and SHA-256, and stages those
exact bytes in a restricted temporary directory for both rendering and upgrade.
Finalized records created by PR #2350 do not contain historical values
coordinates. Consequently, rollback restores manifest-approved chart and image
artifacts using the selected environment's current byte-bound values chain;
historical-configuration replay is deliberately deferred. The command renders
the digest-qualified chart,
checks verifier capabilities, and captures current Helm and pod identity. It
prints only non-secret current-versus-target coordinates; a current chart digest
is reported as unknown because Helm status cannot prove it. It rejects an exact
no-op only when `helm get manifest` and the named `dspace` container identity
prove equivalence to the digest-bound target render; matching version and image
metadata alone still proceeds. All preflight or confirmation failures stop
before mutation.

The normal guarded deploy and redeploy sequence is likewise strict: approved
manifest validation and digest resolution, one exact-release render and structural
validation, evidence reservation, Helm mutation, then evidence finalization. No
render occurs after reservation. A render or validation failure is terminal and
creates no reservation, Helm mutation, Kubernetes rollout call, or final evidence.
Steady-state upgrades do not use `--reuse-values`: the approved digest-qualified
chart defaults, complete ordered Git-controlled values chain, host, immutable image
coordinates, and pull policy are identical for render and mutation. Treat Helm
history as evidence and rollback metadata, not desired-state configuration; migrate
intentional settings into reviewed values files or established Secret references
before upgrading.

After atomically reserving the unique evidence destination, the operation uses
`helm upgrade` with the approved chart digest, complete values chain, and an
application image reference pinned by both its immutable tag and approved digest.
It never uses `--reuse-values`, a semantic tag, or
`helm rollback <revision>`. It then proves the advanced stable Helm revision,
chart identity, Deployment/ReplicaSet ownership, replacement pod UIDs and start
times, readiness, image coordinates and resolved digests, OCI source metadata,
and the strict runtime/frontend/provider/public-journey result (including
`/chat`). The successful non-overwritable record contains those proofs and
values-file hashes; it does not alter the target release record.

The verifier is an executable, not a shell fragment. It must support
`capabilities` and echo the selected environment, release, and namespace with
schema version 1 and the exact ordered capabilities
`applicationVersion`, `runtimeSourceRevision`, `frontendSourceRevision`,
`defaultProvider`, and `publicJourneys`. Its `verify` result must contain exactly
those target coordinates and identity strings plus a non-empty list of
`{name, passed}` journey objects,
including a passing `/chat`. Verifier output and response bodies are not echoed.
Do not infer frontend identity from the semantic application version.

Production rollback is available only when its target is a genuine finalized production record
whose runtime/frontend identity and public journeys satisfy the current verifier contract. A
candidate, staging record, fabricated record, or legacy record without those finalized proofs is
not a rollback target; operators must not substitute an availability-only check.

If anything fails after reservation, the command exits nonzero, leaves a
redacted failed evidence record, and warns that cluster state may have changed.
Inspect `helm history dspace --namespace dspace` and the preserved invocation ID,
then reconcile manually. Never immediately invoke a second rollback. Helm
history remains useful for investigation, but a Helm revision rollback is not
the default DSPACE recovery mechanism. The `tokenplace-rollback` helper is for
Tokenplace and must not be invoked against DSPACE.

## Troubleshooting

Check resolved generic config before changing a release.

```bash
just app-config app=dspace env=staging
```

Check Kubernetes and Helm state.

```bash
just app-status app=dspace env=staging
```

Review logs with the compatibility debug helper.

```bash
just dspace-debug-logs-env env=staging
```

Validate GHCR auth if Helm reports `401`, `403`, or `denied`. Follow the
[GHCR authentication and PAT renewal runbook](../ghcr_authentication.md) to identify
Helm/ORAS consumers, enter a replacement PAT privately, and verify required packages.
`gh auth token` selects the current GitHub CLI credential, not a newly created PAT.

Cloudflare Tunnel routes are external to Helm. Route public hosts to Traefik, typically `http://traefik.kube-system.svc.cluster.local:80`.

```bash
just cf-tunnel-route host=staging.democratized.space
```

```bash
just cf-tunnel-route host=democratized.space
```

## App-specific notes

- DSPACE serves `/config.json`; verify it with `jq` before production promotion and before opening `/chat`.
- Keep release lineage separate from environment routing: image tags identify app code, values overlays identify `staging` or `prod` hostnames and token.place origins.
- The optional `prod.democratized.space` overlay is not the default production path in the generic config.

### Legacy Helm helper reference

The generic app commands above should be the normal operator path. Keep these lower-level helpers available for compatibility with existing tests and older runbooks when debugging raw Helm parameters.

```bash
just helm-oci-install release=dspace namespace=dspace chart=oci://ghcr.io/democratizedspace/charts/dspace values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml version_file=docs/apps/dspace.staging.version tag="$APP_TAG" env=staging
```

```bash
just helm-oci-upgrade release=dspace namespace=dspace chart=oci://ghcr.io/democratizedspace/charts/dspace values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml version_file=docs/apps/dspace.staging.version tag="$APP_TAG" env=staging
```

See [application workload inventory](workload-inventory.md) for supported chart
layouts and the offline render checks.
