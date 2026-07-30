# democratized.space (dspace) on Sugarkube

This is the canonical runbook for deploying DSPACE from GHCR artifacts to Sugarkube. The generic `just app-*` recipes are the preferred future path. The `dspace-oci-*` recipes remain compatibility shims and are scheduled for later removal only after the generic flow has been exercised across routine releases.

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
| Chart version pins | Shared/default `docs/apps/dspace.version`; staging `docs/apps/dspace.staging.version` (`3.1.0`); production `docs/apps/dspace.prod.version` (`3.0.1`) |
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
  The production overlay injects `DSPACE_TOKEN_PLACE_URL=https://token.place` and `DSPACE_TOKEN_PLACE_CHAT_MODEL=llama-3.1-8b-instruct`. Production remains intentionally pinned to the recovered chart `3.0.1` deployment and image `ghcr.io/democratizedspace/dspace:main-1a31a56`; it does not enable metrics or ServiceMonitor settings.
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

Prepare the upstream smoke runner once before any guarded deployment or
verification. The upstream file is checked in with mode `100644`, so make it
executable after installing its dependencies:

```bash
(
  cd "$HOME/dspace"
  pnpm install
  pnpm exec playwright install chromium
  chmod +x scripts/run-remote-chat-smoke.mjs
)
export DSPACE_SMOKE_RUNNER="$HOME/dspace/scripts/run-remote-chat-smoke.mjs"
test -x "$DSPACE_SMOKE_RUNNER"
```

The smoke harness mocks provider transport. Real token.place or OpenAI
credentials are neither required nor accepted.

Pass the candidate and executable runner to staging, then preserve the generated
final record:

```bash
just app-deploy app=dspace env=staging tag="$APP_TAG" \
  manifest=deployment-candidates/dspace/staging.json \
  smoke_runner="$DSPACE_SMOKE_RUNNER"
EVIDENCE=$(python3 scripts/dspace_release_manifest.py evidence-path \
  --manifest deployment-candidates/dspace/staging.json)
STAGING_EVIDENCE="$EVIDENCE"
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
  staging_evidence="$STAGING_EVIDENCE" \
  smoke_runner="$DSPACE_SMOKE_RUNNER" \
  staging_config=/etc/sugarkube/apps/dspace-staging.env \
  staging_kubeconfig="$HOME/.kube/config-dspace-staging"
EVIDENCE=$(python3 scripts/dspace_release_manifest.py evidence-path \
  --manifest deployment-candidates/dspace/prod.json)
git add "$EVIDENCE"
```

The finalized JSON is sufficient to reconstruct the release using the recorded
branch-SHA image tag and digest plus chart version and the exact digest-qualified
chart deployment coordinate, without resolving
`latest`, a branch, an environment tag, or the semantic tag. The runtime contract
delivered by DSPACE [PR #4759](https://github.com/democratizedspace/dspace/pull/4759)
and the remote smoke harness delivered by
[PR #4763](https://github.com/democratizedspace/dspace/pull/4763) let Sugarkube
verify the public build identity, frontend source marker, and isolated `/chat`
journey. Verification also reasserts the connected cluster environment; the
exact deployed Helm release, namespace, chart, and stable revision; complete
rollout counts; and every Running, Ready replica linked by controller UIDs. Each
DSPACE container must use the approved repository, immutable image tag, and
resolved digest, and every direct pod response must agree with the bounded public
identity response.

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
  smoke_runner="$DSPACE_SMOKE_RUNNER"
```

Compatibility shim while migration is in progress:

```bash
just dspace-oci-deploy env=staging tag="$APP_TAG" \
  manifest=deployment-candidates/dspace/staging.json \
  smoke_runner="$DSPACE_SMOKE_RUNNER"
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

This configuration change does not promote or mutate production. Promote only after staging sign-off. Prefer the generic command; it uses the prod values chain, resolves chart `3.0.1` from `docs/apps/dspace.prod.version`, and can read `docs/apps/dspace.prod.tag` (`main-1a31a56`) when `tag=` is omitted.

```bash
just app-promote-prod app=dspace tag="$APP_TAG" \
  manifest=deployment-candidates/dspace/prod.json \
  staging_evidence="$STAGING_EVIDENCE" \
  smoke_runner="$DSPACE_SMOKE_RUNNER" \
  staging_config=/etc/sugarkube/apps/dspace-staging.env \
  staging_kubeconfig="$HOME/.kube/config-dspace-staging"
```

Compatibility shim:

```bash
just dspace-oci-promote-prod tag="$APP_TAG" \
  manifest=deployment-candidates/dspace/prod.json \
  staging_evidence="$STAGING_EVIDENCE" \
  smoke_runner="$DSPACE_SMOKE_RUNNER" \
  staging_config=/etc/sugarkube/apps/dspace-staging.env \
  staging_kubeconfig="$HOME/.kube/config-dspace-staging"
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
  smoke_runner="$DSPACE_SMOKE_RUNNER"
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
  smoke_runner="$DSPACE_SMOKE_RUNNER" \
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

The standard operator path always uses the checked-in
`scripts/dspace_runtime_verifier.py`; do not substitute an availability-only
check. The separate rollback `verifier=` option exists only for exceptional
compatibility with a legacy executable implementing the older verifier contract.
Such a verifier is an executable, not a shell fragment, and must support
`capabilities` and echo the selected environment, release, and namespace with
schema version 1 and the exact ordered capabilities
`applicationVersion`, `runtimeSourceRevision`, `frontendSourceRevision`,
`defaultProvider`, and `publicJourneys`. Its `verify` result must contain exactly
those target coordinates and identity strings plus a non-empty list of
`{name, passed}` journey objects,
including a passing `/chat`. Verifier output and response bodies are not echoed.
Do not infer frontend identity from the semantic application version.

The checked-in verifier uses the runtime/frontend identity from DSPACE
[PR #4759](https://github.com/democratizedspace/dspace/pull/4759) and the remote
public-journey harness from
[PR #4763](https://github.com/democratizedspace/dspace/pull/4763), so staging and
production rollback use the same runtime, replica, provider, and `/chat` proof as
normal deployment finalization.

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

## Mandatory release identity and `/chat` gate

A DSPACE checkout supplies the non-destructive browser harness. If the setup in
the deployment section has not already been completed, install its dependencies
and make the upstream mode-`100644` script executable. Always provide the
executable itself—not a shell command or fragment:

```bash
(
  cd "$HOME/dspace"
  pnpm install
  pnpm exec playwright install chromium
  chmod +x scripts/run-remote-chat-smoke.mjs
)
export DSPACE_SMOKE_RUNNER="$HOME/dspace/scripts/run-remote-chat-smoke.mjs"
test -x "$DSPACE_SMOKE_RUNNER"

just dspace-release-verify \
  env=staging \
  manifest=deployment-evidence/dspace/staging/<finalized-record>.json \
  smoke_runner="$DSPACE_SMOKE_RUNNER" \
  config=/etc/sugarkube/apps/dspace-staging.env \
  kubeconfig="$HOME/.kube/config-dspace-staging"

just dspace-release-verify \
  env=prod \
  manifest=deployment-evidence/dspace/prod/<finalized-record>.json \
  smoke_runner="$DSPACE_SMOKE_RUNNER" \
  config=/etc/sugarkube/apps/dspace-prod.env \
  kubeconfig="$HOME/.kube/config-dspace-prod"
```

The verifier checks the public build identity and frontend marker, then checks
all ready, release-owned replicas directly through the read-only Kubernetes API
pod proxy. It proves the approved image digest, full source revision, replica
agreement, public/direct agreement, and the isolated `/chat` journey. The
harness mocks provider transport; real token.place or OpenAI credentials are
neither required nor accepted. For a token.place-default manifest the origin and
model come from the selected, ordered values chain. For an OpenAI-default
manifest those token.place arguments are omitted, while OpenAI discoverability
and missing-key gating remain part of the harness proof.

Create staging evidence by deploying the approved staging candidate with the
same executable:

```bash
just app-deploy app=dspace env=staging tag=main-REPLACE_SHORTSHA \
  manifest=deployment-candidates/dspace/staging.json \
  smoke_runner="$DSPACE_SMOKE_RUNNER"
```

Only after the post-rollout verifier succeeds is the non-overwriting staging
record written under `deployment-evidence/dspace/staging/`; production records
are written under `deployment-evidence/dspace/prod/`. Production requires the
finalized staging record as an additional gate. Assign its exact path, rather
than a candidate or reservation path:

```bash
STAGING_EVIDENCE=deployment-evidence/dspace/staging/<finalized-record>.json
just app-promote-prod \
  app=dspace \
  tag=main-REPLACE_SHORTSHA \
  manifest=deployment-candidates/dspace/prod.json \
  staging_evidence="$STAGING_EVIDENCE" \
  staging_config=/etc/sugarkube/apps/dspace-staging.env \
  staging_kubeconfig="$HOME/.kube/config-dspace-staging" \
  smoke_runner="$DSPACE_SMOKE_RUNNER"
```

Before production rendering, reservation, or mutation, the command validates
that staging evidence is finalized, compares all immutable release coordinates,
rechecks the recorded live Helm revision, and reruns the full verifier against
staging through the explicitly supplied `staging_config` and
`staging_kubeconfig`. It runs the same verifier after production rollout and before
the final production evidence is written. A post-mutation failure leaves the reservation
for the existing reconciliation procedure; it never writes successful evidence,
retries, downgrades, or automatically rolls back. Use the reservation recovery
instructions above after investigating the bounded failure category.

For `provider=token-place`, verification derives the expected token.place URL
and model from the selected ordered values chain. For `provider=openai`, it
omits token.place arguments and verifies the OpenAI-default missing-key behavior.
In both modes the isolated harness rejects real provider credentials; none are
needed for staging, production, promotion, or rollback verification.
