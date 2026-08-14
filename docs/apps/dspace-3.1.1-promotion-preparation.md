# DSPACE 3.1.1 promotion preparation

This repository change is **preparation only**. It does not contact a cluster, publish an artifact,
create approval metadata, create or finalize deployment evidence, recover production, or promote
production. Production remains release/namespace `dspace`/`dspace`, revision 10, chart 3.0.3 and
application 3.0.1. The reviewed successor is recorded in
`dspace.promotion-target.json`; its immutable deployment coordinate is `main-22f506e`, never the
semantic release tag.

## Read-only planning gate

`scripts/dspace_promotion_plan.py` accepts only bounded, sanitized JSON reports. The artifact report
must independently establish the exact image digest, Linux/ARM64 image availability, OCI source
annotation, chart digest, chart `version`/`appVersion`/source revision, and the `v3.1.1` and
`chart-v3.1.2` tags. The source report must establish privacy-safe definitions for all six required
`dspace_*` families. The incident classifier may contain counts and status only: never a Secret
value or raw metrics payload. The preserved failed reconciliation is validated independently
against the finalized production baseline and maintenance target.

The command runs only `helm template` against the chart **digest**, renders staging and eventual
production with `main-22f506e`, two replicas and `image.pullPolicy=Always`, and prints a sanitized
plan. It rejects rendered Secrets, staging data in production, semantic image coordinates and
coordinate drift. It has no `--reuse-values`, Helm upgrade, kubectl, rollout, Secret mutation, or
evidence-finalization path. The old classifier explains why 3.0.1 cannot satisfy the metrics gate;
it is not deployment evidence.

## Required future sequence

1. Record genuine, reviewed operator approval metadata outside this preparation change.
2. Create a fresh staging candidate for the exact application 3.1.1/chart 3.1.2 coordinates.
   Existing finalized application 3.1.0/chart 3.1.1 evidence is historical and cannot authorize it.
3. Deploy staging through the existing guarded release machinery, not this planner.
4. Prove exactly two Ready replicas running the exact image digest; prove runtime and frontend
   source identity, replica agreement, and public/direct agreement. The intended production default
   provider remains `openai`.
5. Pass a bounded remote `/chat` smoke test. Prove two healthy authenticated Prometheus targets,
   no scrape errors, and all six families: `dspace_build_info`, `dspace_dchat_requests_total`,
   `dspace_dependency_requests_total`, `dspace_http_request_duration_seconds_bucket`,
   `dspace_http_requests_total`, and `dspace_instrumentation_up`. Exercise a real server-observed
   chat/dependency journey where needed to produce truthful samples.
6. Finalize the exact staging evidence to a non-overwritable destination.
7. Only after all prior gates pass may a separate repository task add a one-shot production
   revision-10 successor promotion. That future work must still reject `--reuse-values`, values
   drift, staging configuration, rendered Secrets, and unproved runtime or metrics results.

The `dspace-prod-metrics-pull-policy-recover` operation remains ineligible for this incident. Its
fail-closed metrics verifier and preflight must remain intact; do not rerun, weaken, bypass, or
repurpose it as an application promotion. Do not roll back or uninstall Helm and do not read,
rotate, or delete the metrics Secret. Issues #2325 and #2329 stay closed unless a human decides
otherwise; issue #2408 is unrelated and must not be modified or conflated with this preparation.
