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

Find the successful image workflow in the DSPACE app repo and copy the immutable branch-SHA or release tag. The GitHub Actions workflow page is where recent builds are found; the GHCR package page is where published image tags are cross-checked. Do not deploy `latest`, a bare branch name, or an environment name.

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
  manifest=deployment-candidates/dspace/staging.json
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
  manifest=deployment-candidates/dspace/prod.json
EVIDENCE=$(python3 scripts/dspace_release_manifest.py evidence-path \
  --manifest deployment-candidates/dspace/prod.json)
git add "$EVIDENCE"
```

The finalized JSON is sufficient to reconstruct the release using the recorded
branch-SHA image tag and digest plus chart version and the exact digest-qualified
chart deployment coordinate, without resolving
`latest`, a branch, an environment tag, or the semantic tag. Until DSPACE #4732
adds direct runtime identity, `runtimeSourceRevisionMethod` is strictly
`podImageID+ociRevisionAnnotation`: every pod image ID must equal the approved
digest and that exact OCI artifact's revision annotation must equal the full
approved SHA. Finalization also reasserts the connected cluster environment,
requires Helm to report the selected release and namespace as deployed with the
exact approved DSPACE chart version, and accepts only Running, Ready pods owned
through the selected Helm release's Deployment and ReplicaSet. Each DSPACE
container must use the approved repository and immutable image tag before its
resolved image ID is accepted. No HTTP build-identity check is claimed.

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
just app-deploy app=dspace env=staging tag="$APP_TAG" manifest=deployment-candidates/dspace/staging.json
```

Compatibility shim while migration is in progress:

```bash
just dspace-oci-deploy env=staging tag="$APP_TAG" manifest=deployment-candidates/dspace/staging.json
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
just app-promote-prod app=dspace tag="$APP_TAG" manifest=deployment-candidates/dspace/prod.json
```

Compatibility shim:

```bash
just dspace-oci-promote-prod tag="$APP_TAG" manifest=deployment-candidates/dspace/prod.json
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

The primary recovery procedure is a manifest rollback: select the **finalized**
release-evidence JSON from the previous approved deployment. The command derives
all deployable coordinates from that record, accepts no tag or chart override,
and never deploys `semanticTag`.

```bash
TARGET=deployment-evidence/dspace/staging/previous-finalized-release.json
ROLLBACK_EVIDENCE=deployment-evidence/dspace/staging/rollback-$(date -u +%Y%m%dT%H%M%SZ).json
just dspace-manifest-rollback env=staging manifest="$TARGET" \
  evidence="$ROLLBACK_EVIDENCE" verifier=/path/to/dspace-runtime-verifier
```

Staging is non-interactive and rejects a supplied confirmation. Production
requires the exact value bound to DSPACE, `prod`, and the target full SHA; a
generic `yes` is invalid:

```bash
TARGET=deployment-evidence/dspace/prod/previous-finalized-release.json
TARGET_SHA=$(jq -er .sourceRevision "$TARGET")
just dspace-manifest-rollback env=prod manifest="$TARGET" \
  evidence=deployment-evidence/dspace/prod/rollback-$(date -u +%Y%m%dT%H%M%SZ).json \
  verifier=/path/to/dspace-runtime-verifier confirm="DSPACE:prod:${TARGET_SHA}"
```

Before reserving evidence or mutation, the command revalidates final evidence and
OCI metadata, asserts the cluster, hashes every ordered values file, renders the
digest-qualified chart, checks verifier capabilities, captures Helm and pod
state, prints provable current-versus-target coordinates, rejects a no-op, and
validates confirmation. Helm cannot expose the digest used by an installed
revision, so no current chart digest is invented.

It then exclusively reserves `<evidence>.reservation` and binds the
`helm upgrade` description to that invocation. The complete values chain and
approved immutable tag are explicit; neither `--reuse-values`, a semantic tag,
nor `helm rollback` is used. Proof requires a stable advanced Helm revision,
chart identity, Deployment/ReplicaSet ownership, replacement UIDs/start times
when artifacts differ, no terminating or old serving pods, readiness, image
coordinates and IDs, OCI provenance, and strict runtime, frontend, provider, and
public-journey results including `/chat`.

Success writes separate non-overwritable evidence containing the target
fingerprint, invocation, values hashes, Sugarkube revision, before/after state,
and verification. Never edit the historical target. After failure following
reservation, preserve the diagnostic sidecar because cluster state may have
changed; reconcile manually. No automatic second rollback is attempted.

The verifier is an executable, not a shell string. `VERIFIER capabilities` must
return exactly this contract (including check order):

```json
{
  "schemaVersion": "sugarkube.dspace-runtime-verifier/v1",
  "checks": ["applicationVersion", "runtimeSourceRevision", "frontendSourceRevision", "defaultProvider", "publicHome", "publicHealth", "chat"],
  "acceptsRequestOnStdin": true
}
```

`VERIFIER verify` receives non-secret expectations on standard input and returns
exact application version, full runtime and frontend SHAs, provider, and ordered
boolean journey results. It must not emit secrets, headers, or response bodies.
Real production rollback remains unavailable until DSPACE
[#4732](https://github.com/democratizedspace/dspace/issues/4732) and
[#4733](https://github.com/democratizedspace/dspace/issues/4733) supply the
runtime-identity and remote-smoke implementations. Availability-only checks,
semantic-version inference, and fabricated frontend identity are not substitutes.

`helm history dspace -n dspace` remains useful for investigation, but
`helm rollback <revision>` is not the default recovery mechanism. The
`tokenplace-rollback` helper is Tokenplace-only and must not be used for DSPACE.

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
