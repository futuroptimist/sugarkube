# danielsmith.io visitor-journey observability

Sugarkube consumes the sanitized result contract owned by danielsmith.io at revision
`7c972a57d5235591b0449d5d2a81dd8359bd97a5`. It does not duplicate the browser
assertions. The two descriptors in
`config/observability/danielsmith-visitor-journey.json` are disabled by default;
merging this integration does not authorize scheduling or execution in either
environment.

The consumer accepts exactly `state`, `freshness`, `aggregateDurationMs`, and
`failureStage`. State is `success` or `failure`; a successful result has a null
failure stage. Failures use only `homepage_delivery`, `javascript_initialization`,
`essential_assets`, `accessible_fallback`, `resume_pdf`, `timeout`, or
`producer_interrupted`. Duration is finite and nonnegative and freshness is Unix
seconds. Extra fields, non-finite numbers, contradictory results, and future times
fail closed.

Only bounded application, environment, producer-state, and failure-stage labels are
exported. Page contents, visitor data, request identities, URLs, headers, cookies,
and credentials are rejected by the exact schema. Optional immersive rendering is
application-owned, deliberately separate from essential visitor health, and is not
exported because revision `7c972a5` defines no sanitized optional-renderer field.

The offline publishing entry point is
`scripts/danielsmith_visitor_metrics.py --environment ENV --result RESULT.json
--output OUTPUT.prom`. It revalidates the committed descriptor and sanitized JSON,
then atomically writes only Prometheus text format. For a disabled descriptor omit
`--result`; supplying a result while disabled fails closed. Tests exercise this
handoff with temporary files only.

No application producer currently calls this entry point, and no node-exporter
textfile-collector installation or scrape target is provisioned by this change.
Those application-owned production and installation boundaries remain unresolved;
this repository does not execute, schedule, deploy, or claim runtime coverage for
the journey.

## Alerts

`DanielsmithVisitorJourneyFailed` reports a current executed essential-journey
failure. Both alert expressions compare Prometheus evaluation time with the exported
completion timestamp, so a frozen success or failure becomes stale after the
15-minute cadence plus 120-second timeout. The independent
`danielsmith_visitor_journey_monitoring_expected` recording rules remain zero in
both environments; a future authorized activation must change the corresponding
declaration as part of provisioning so loss of all exporter series is detectable.
`DanielsmithVisitorJourneyStaleOrUnavailable` reports missing or stale results only
when monitoring is declared expected. Disabled monitoring is visible on the
dashboard but never treated as success and never pages.

A later, separately authorized change must install and activate the pinned
application producer, qualify staging, and only then consider production.
