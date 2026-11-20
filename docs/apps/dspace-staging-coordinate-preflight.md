# DSPACE v3.1.0 staging coordinate preflight

This is a **read-only** bridge for DSPACE’s separate
`dspace-staging-coordinates-v1` receipt as reviewed in [DSPACE #4903][dspace-pr],
at commit `157a545b633dfac8d47e9741325fd94514ebde30`. It reports the exact image
and chart digests it checked against GHCR. It cannot install Helm charts, change
a cluster, grant a deployment, or produce a release manifest. It does not use
the occupied semantic image alias or infer that any chart version is available.

## Operator inputs

Keep these three small JSON files privately and independently verify the
source of each. Do not include credential material or signed download URLs.

1. DSPACE’s `dspace-staging-coordinates.json`, generated from the independently
   confirmed commit and approved image/chart digests. Its metadata verification
   is not execution or deployment evidence.
2. The **unaltered** `candidate-image-summary.json` from a successful,
   owner-operated **Verify immutable candidate image** run on DSPACE
   `main`. Acquire it from the exact successful workflow run and attempt using
   authenticated read access. Independently confirm the official repository,
   workflow, owner dispatch, artifact ID, run attempt, workflow SHA and both
   successful platform probes before accepting it. Hash the raw summary bytes,
   not the artifact ZIP or pretty-printed JSON.
3. An owner-approved staging preflight record, maintained separately from the
   other two files. It must have exactly these fields:
   - `schema`: `dspace-staging-preflight-approval-v1`; `environment`: `staging`.
   - `approvalRef`, `sourceRevision`, `applicationVersion`, `imageDigest`,
     `chartVersion`, `chartDigest`: the exact independently approved values.
   - `nativeArtifactId`, `nativeRunId`, `nativeRunAttempt`: strings containing
     the independently confirmed GitHub identifiers.
   - `nativeWorkflowSha`: the exact 40-character workflow commit.
   - `nativeSummaryDigest`: `sha256:` followed by the SHA-256 of the exact
     approved summary bytes.

The adapter binds the summary to that independent record by its raw hash,
source, workflow SHA, run ID and attempt; it does not contact GitHub to
authenticate a local file, approval reference, or artifact ID. The operator
must authenticate those with the owner and GitHub before use. Do not create
the approval from untrusted receipt contents or treat a matching local record
as a signature.

## Read-only use

On a trusted staging operations host, arrange the existing read-only GHCR
access for ORAS before invoking the command. The tool uses ORAS’s existing
authentication configuration; it neither accesses tokens directly nor checks
which credential the client selected. A missing or denied read is an error,
not evidence of absence. The command checks that the current context in
`~/.kube/config-sugarkube-staging` is exactly `sugar-staging` and uses the
repository cluster identity check (a read of node labels) to confirm staging.
The context and authenticated connection are not a replacement for the owner’s
independent staging approval.

```sh
python3 scripts/dspace_staging_coordinates.py preflight \
  --environment staging \
  --receipt dspace-staging-coordinates.json \
  --approval dspace-staging-preflight-approval.json \
  --native-summary candidate-image-summary.json
```

Authenticated registry reads target only the canonical DSPACE repositories and
immutable digests. They re-hash the raw image index, both image manifests and
configs, the chart manifest and chart config; they compare exact platform,
source, and app/chart coordinates. They do not download or validate chart/image
layers. The chart digest in the output is the OCI manifest digest, not the
archive digest. There is no fallback to any tag or alternate registry, context,
or kubeconfig. An error emits no coordinate output.

Success prints `sugarkube-dspace-staging-preflight-v1` JSON with
`deploymentAuthorized: false`. Preserve it as read-only staging evidence only.
It is intentionally not compatible with the existing `candidate`, `final`,
or production `staging-gate` interfaces. No existing semantic-release or
production gate is changed. Do not translate evidence into a normal release
manifest, supply a fictitious alias, or pass these coordinates to a mutation
command. A separately approved staging operation would need to bind and
validate installed chart/image digests and runtime evidence before completion.
Neither this command nor a valid result authorizes that operation.

[dspace-pr]: https://github.com/democratizedspace/dspace/pull/4903
