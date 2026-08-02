# democratized.space (dspace) on Sugarkube

This is the canonical runbook for deploying DSPACE from GHCR artifacts to Sugarkube. The generic `just app-*` recipes are the preferred future path. The `dspace-oci-*` recipes remain compatibility shims and are scheduled for later removal only after the generic flow has been exercised across routine releases.

## Production Helm reconciliation for application 3.0.1

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
  .chartSourceRevision == "63063e287adb92a4158ce2c8e7d378b73f52c1c5" and
  .imageTag == "main-1a31a56" and
  .imageDigest == "sha256:23dbc573377549136c1f10b05706b3c176ffbabaf04a3194381a24752104a401" and
  .chartVersion == "3.0.2" and
  .chartDigest == "sha256:8b862135e52146f301a41259d6dabb053ed891d798fc1c8c95ca775b2b8e9575"' "$RECOVERY"
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
# approved 3.0.2 production pin for this recovery only.
RECOVERY_CONFIG=$(mktemp)
trap 'rm -f "$RECOVERY_CONFIG"' EXIT
python3 - "$RECOVERY_CONFIG" <<'PY'
from pathlib import Path
import sys

source = Path("docs/examples/apps/dspace.env").read_text(encoding="utf-8")
old = "SUGARKUBE_VERSION_FILE_STAGING=docs/apps/dspace.staging.version"
new = "SUGARKUBE_VERSION_FILE_STAGING=docs/apps/dspace.prod.version"
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
HTTP_PORT=$(kubectl --kubeconfig "$PROD_KUBECONFIG" -n dspace get deployment dspace \
  -o jsonpath='{.spec.template.spec.containers[?(@.name=="dspace")].ports[?(@.name=="http")].containerPort}')
timeout 10s kubectl --kubeconfig "$PROD_KUBECONFIG" get --raw \
  "/api/v1/namespaces/dspace/pods/$POD:$HTTP_PORT/proxy/build-meta.json" \
  | head -c 16384 >"$DIRECT_BUILD"
jq -e '{gitSha, generatedAt, source}' "$DIRECT_BUILD" \
  >"$CAPTURE/direct-build-identity.json"
```

Do not run `dspace-release-verify` against the pre-change 3.0.2 candidate: the full verifier
correctly rejects the currently installed 3.0.1 chart. The bounded captures above retain only the
three allowlisted legacy identity fields and cap each response at 16 KiB. Before evidence
reservation or
mutation, run the existing recipe's exact read-only digest-qualified render and structural
validation sequence:

```bash
eval "$(python3 scripts/app_config.py shell --app dspace --env prod \
  --config docs/examples/apps/dspace.env --tag main-1a31a56 --require-tag)"
CHART_VERSION=$(sed -e 's/#.*$//' -e '/^[[:space:]]*$/d' \
  "$SUGARKUBE_VERSION_FILE" | head -n1)
test "$CHART_VERSION" = 3.0.2
CHART_COORDINATE=$(python3 scripts/dspace_release_manifest.py preflight \
  --manifest deployment-candidates/dspace/recovery-prod.json --environment prod \
  --image-tag "$SUGARKUBE_TAG" --chart-version "$CHART_VERSION" \
  --chart-ref "$SUGARKUBE_CHART" --print-chart-coordinate)
test "$CHART_COORDINATE" = \
  'oci://ghcr.io/democratizedspace/charts/dspace@sha256:8b862135e52146f301a41259d6dabb053ed891d798fc1c8c95ca775b2b8e9575'
PROD_HOST=$(python3 scripts/app_chart.py resolve-host --values "$SUGARKUBE_VALUES")
python3 scripts/app_chart.py preflight \
  --app "$SUGARKUBE_APP" --env "$SUGARKUBE_ENV" --tag "$SUGARKUBE_TAG" \
  --chart "$CHART_COORDINATE" --version "${SUGARKUBE_VERSION:-}" \
  --version-file "$SUGARKUBE_VERSION_FILE" --values "$SUGARKUBE_VALUES" \
  --release "$SUGARKUBE_RELEASE" --namespace "$SUGARKUBE_NAMESPACE" \
  --host "$PROD_HOST" --pull-policy Always
```

This must prove chart 3.0.2 at the approved OCI digest and the immutable application image while
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
image digest; installed chart version and OCI provenance must be 3.0.2 and its chart revision/digest.
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
manifest. The verifier checks public build identity and frontend marker, every ready serving
replica's image coordinate, digest, build identity, and frontend marker, then invokes DSPACE's
non-destructive remote `/chat` harness. It uses read-only Kubernetes API pod proxies. Successful
bounded results are included in finalized evidence as `runtimeVerification`; response bodies,
child output, browser artifacts, headers, cookies, credentials, and request payloads are not saved.

The default identity contract is `build-info-v1`: public and direct `/build-info.json` plus the
root HTML build-revision marker must agree for every replica. The verifier derives the proxy port
from the unique `http` port on the validated Deployment's unique `dspace` container and requires
the same valid named port on every pod; it does not assume a numeric port. The sole exception is
`legacy-build-meta-v1`, selected only when every approved 3.0.1 recovery coordinate (schema,
application and chart revisions, image and chart tags/digests, semantic tag, and OpenAI provider)
matches exactly. In that mode, bounded public and direct `/build-meta.json` documents must contain
the approved full `gitSha`, a valid non-empty `generatedAt`, and a non-empty `source`, and must agree
across all replicas. Bounded non-empty root documents are still checked, but the legacy HTML is not
treated as a revision marker. Sugarkube always passes the selected contract explicitly to DSPACE's
smoke runner. This exception is not a fallback after modern verification fails and does not alter
immutable coordinates, candidate approval, or finalized evidence.

Prepare a DSPACE checkout with `pnpm install` and `pnpm exec playwright install chromium`. The
runner must be executable. It mocks provider transport, so no token.place or OpenAI credentials
are required or accepted:

```bash
DSPACE_SMOKE_RUNNER="$HOME/dspace/scripts/run-remote-chat-smoke.mjs"
STAGING_KUBECONFIG="$HOME/.kube/config-sugarkube-staging"
PROD_KUBECONFIG="$HOME/.kube/config-sugarkube-prod"
chmod +x "$DSPACE_SMOKE_RUNNER"

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
Helm revision remains live, and reruns complete staging verification:

```bash
just app-promote-prod \
  app=dspace \
  tag=main-REPLACE_SHORTSHA \
  manifest=deployment-candidates/dspace/prod.json \
  staging_evidence=deployment-evidence/dspace/staging/<finalized-record>.json \
  smoke_runner="$DSPACE_SMOKE_RUNNER" \
  kubeconfig="$PROD_KUBECONFIG" \
  staging_kubeconfig="$STAGING_KUBECONFIG"
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

## Artifact model

- App repository responsibilities: build `ghcr.io/democratizedspace/dspace`, publish immutable image tags, maintain the Helm chart, and publish immutable chart versions to `oci://ghcr.io/democratizedspace/charts/dspace`.
- Sugarkube responsibilities: select `dev`, `staging`, or `prod`; load `docs/examples/apps/dspace.env` or a local override; select kubeconfig/context; install or upgrade Helm; verify rollout status, logs, and public paths.
- Cloudflare responsibilities: DNS and Tunnel routes to Traefik are outside Helm and must exist before public verification.

| Coordinate | Value |
| --- | --- |
| Image | `ghcr.io/democratizedspace/dspace` |
| Chart | `oci://ghcr.io/democratizedspace/charts/dspace` |
| Release | `dspace` |
| Namespace | `dspace` |
| App config | `docs/examples/apps/dspace.env` |
| Chart version pins | Shared/default `docs/apps/dspace.version`; staging `docs/apps/dspace.staging.version` (`3.1.0`); production `docs/apps/dspace.prod.version` (`3.0.2`) |
| Production tag pin | `docs/apps/dspace.prod.tag` |
| Verify paths | `/config.json`, `/healthz`, `/livez` |

### Artifact links

Use these links before changing a deployment so the workflow runs, package versions, and source paths all agree.

| Artifact | Link |
| --- | --- |
| App repository | [DSPACE app repository](https://github.com/democratizedspace/dspace) |
| Image workflow | [Recent image workflow runs](https://github.com/democratizedspace/dspace/actions/workflows/ci-image.yml) |
| Successful main image runs | [Successful main image workflow runs](https://github.com/democratizedspace/dspace/actions/workflows/ci-image.yml?query=branch%3Amain+is%3Asuccess) |
| Successful v3 image runs | [Successful v3 image workflow runs](https://github.com/democratizedspace/dspace/actions/workflows/ci-image.yml?query=branch%3Av3+is%3Asuccess) |
| GHCR image package | [GHCR image package versions](https://github.com/democratizedspace/dspace/pkgs/container/dspace) |
| Chart workflow | [Recent chart workflow runs](https://github.com/democratizedspace/dspace/actions/workflows/ci-helm.yml) |
| GHCR chart package | No public package page is associated yet; use the [DSPACE chart package lookup](https://github.com/orgs/democratizedspace/packages?repo_name=dspace&q=charts%2Fdspace) and `helm show chart` below until the chart package appears. |
| Dockerfile | [Application Dockerfile](https://github.com/democratizedspace/dspace/blob/main/Dockerfile) |
| Chart source | [Helm chart source](https://github.com/democratizedspace/dspace/tree/main/charts/dspace) |
| App release guide | [Sugarkube release guide in the app repo](https://github.com/democratizedspace/dspace/blob/main/docs/ops/sugarkube-release.md) |

## Environment topology

- `env=dev`: future single-node/non-HA environment using `docs/examples/dspace.values.dev.yaml`.
  The dev overlay intentionally does not choose a token.place origin; developers who need local runtime routing can copy `docs/examples/apps/dspace.env` to a local app config and add chart-supported `env` entries to their private values file.
- `env=staging`: HA staging on the staging Sugarkube cluster with host `staging.democratized.space` and values `docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml`.
  The staging overlay injects `DSPACE_TOKEN_PLACE_URL=https://staging.token.place` and `DSPACE_TOKEN_PLACE_CHAT_MODEL=llama-3.1-8b-instruct`, uses chart `3.1.0`, and persists the authenticated metrics ServiceMonitor configuration discovered by kube-prometheus-stack. The metrics bearer value is not committed; operators manage the existing `dspace-staging-metrics-token` Secret out of band.
- `env=prod`: HA production on the production Sugarkube cluster with host `democratized.space` and values `docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.prod.yaml`.
  The production overlay injects `DSPACE_TOKEN_PLACE_URL=https://token.place` and `DSPACE_TOKEN_PLACE_CHAT_MODEL=llama-3.1-8b-instruct`. Production is pinned to recovery chart `3.0.2` and image `ghcr.io/democratizedspace/dspace:main-1a31a56`; it does not enable metrics or ServiceMonitor settings.
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

If no suitable image exists, publish it from the app repo workflow, then return here with the immutable tag it produced.

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

If the chart changed, bump the chart version in the DSPACE app repo and publish it there with [the chart workflow](https://github.com/democratizedspace/dspace/actions/workflows/ci-helm.yml); do not republish a different chart under an existing OCI version.

```bash
gh workflow run ci-helm.yml --repo democratizedspace/dspace --ref main
```

## Deploy staging

### Release-manifest approval and evidence flow

Download the `dspace-release-manifest` artifact from the successful upstream
image workflow and extract `dspace-release-manifest/dspace-release-manifest.json`.
Do not copy coordinates from mutable package tags. Create a canonical staging
candidate with an explicit UTC approval time, approver identity, and one of the
configuration contract's exact provider values (`token-place` or `openai`):

```bash
python3 scripts/dspace_release_manifest.py candidate \
  --upstream dspace-release-manifest/dspace-release-manifest.json \
  --output deployment-candidates/dspace/staging.json \
  --environment staging --provider token-place \
  --approved-at 2026-07-26T12:00:00Z --approved-by '<operator-or-review-record>'
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
  --approved-at 2026-07-26T13:00:00Z --approved-by '<operator-or-review-record>'
just app-promote-prod app=dspace tag="$APP_TAG" \
  manifest=deployment-candidates/dspace/prod.json \
  staging_evidence=deployment-evidence/dspace/staging/<finalized-record>.json \
  smoke_runner="$DSPACE_SMOKE_RUNNER" \
  kubeconfig="$PROD_KUBECONFIG" \
  staging_kubeconfig="$STAGING_KUBECONFIG"
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

This repository change only persists the staging configuration; it does not deploy anything to a cluster. After it is merged, deploy the new immutable, environment-neutral DSPACE image that contains runtime `/config.json` support. The image tag stays the same as it moves between staging and production; the Sugarkube values overlays, not image names, select the token.place origin.

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
      .tokenPlace.url == "https://staging.token.place"
      and .tokenPlace.model == "llama-3.1-8b-instruct"
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

1. Deploy the token.place image containing wildcard API v1 CORS.
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

For staging, the browser smoke must show DSPACE calling `https://staging.token.place/api/v1/chat/completions`; for production it must show `https://token.place/api/v1/chat/completions`. Confirm the `OPTIONS` preflight succeeds, the `POST` succeeds or returns a readable API-owned error, no `Authorization` header is sent, no token.place credentials are sent, fetch `credentials` are omitted, and the request does not set `stream: true`.

## Promote production

This configuration change does not promote or mutate production. Promote only after staging sign-off. Prefer the generic command; it uses the prod values chain, resolves chart `3.0.2` from `docs/apps/dspace.prod.version`, and can read `docs/apps/dspace.prod.tag` (`main-1a31a56`) when `tag=` is omitted.

```bash
just app-promote-prod app=dspace tag="$APP_TAG" \
  manifest=deployment-candidates/dspace/prod.json \
  staging_evidence=deployment-evidence/dspace/staging/<finalized-record>.json \
  smoke_runner="$DSPACE_SMOKE_RUNNER" \
  kubeconfig="$PROD_KUBECONFIG" staging_kubeconfig="$STAGING_KUBECONFIG"
```

Compatibility shim:

```bash
just dspace-oci-promote-prod tag="$APP_TAG" \
  manifest=deployment-candidates/dspace/prod.json \
  staging_evidence=deployment-evidence/dspace/staging/<finalized-record>.json \
  smoke_runner="$DSPACE_SMOKE_RUNNER" \
  kubeconfig="$PROD_KUBECONFIG" staging_kubeconfig="$STAGING_KUBECONFIG"
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
      .tokenPlace.url == "https://token.place"
      and .tokenPlace.model == "llama-3.1-8b-instruct"
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

Validate GHCR auth if Helm reports `401`, `403`, or `denied`. Use a non-interactive login so recovery works in copy-paste shells; `gh auth token` must have package read access for private packages.

```bash
HELM_STDIN_FLAG="--pass""word-stdin"
gh auth token | helm registry login ghcr.io \
  --username "$(gh api user --jq .login)" \
  "$HELM_STDIN_FLAG"
```

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
