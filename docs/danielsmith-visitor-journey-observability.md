# danielsmith.io visitor-journey observability

Sugarkube consumes the sanitized result owned by `danielsmith.io`; it does not repeat the browser
assertions. The accepted fields are `state` (`success` or `failure`), Unix-second `freshness`, a
finite nonnegative `aggregateDurationMs`, and one finite `failureStage` (or `null` on success).

Both staging and production descriptors are disabled by default. Enabling either producer and
supplying its bounded request multiplicity requires separate authorization and qualification. A
disabled producer is not successful: lifecycle metrics distinguish `disabled`, `unavailable`,
`stale`, `failed`, `recovered`, and `successful`.

The essential journey includes the accessible fallback. Immersive rendering remains an optional,
application-owned check and is intentionally absent from the essential success metric and alert.
The upstream sanitized result contract does not currently expose an optional-renderer state, so
Sugarkube does not invent one. No request identity, response body, visitor data, URL, header, cookie,
token, or credential is accepted as telemetry.

The dashboard shows monitoring state, essential success, freshness, duration, and bounded failure
stage for the selected environment. The alert fires only when monitoring has explicitly been
enabled and its essential lifecycle is failed, stale, or unavailable. Recovery clears the alert.
