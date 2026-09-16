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

## Alerts

`DanielsmithVisitorJourneyFailed` reports an executed essential-journey failure.
`DanielsmithVisitorJourneyStaleOrUnavailable` reports missing or stale results only
when monitoring is enabled. Disabled monitoring is visible on the dashboard but
never treated as success and never pages.

A later, separately authorized change must install and activate the pinned
application producer, qualify staging, and only then consider production.
