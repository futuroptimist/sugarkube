# Daniel GitHub-cache collection contract

Sugarkube pins the application-owned cache telemetry contract to danielsmith.io revision
`c4d45d96f593d0075096c55ea0a71215350b5ed3`. Both staging and production declarations are
disabled by default. Activation requires a separate reviewed change to both the producer and the
matching `daniel_github_cache_monitoring_expected` recording rule.

## Handoff and ownership

The generic offline adapter reads a previously transported `cache` snapshot and writes a
node-exporter textfile atomically. It performs no network I/O, imports no HTTP or GitHub client,
and cannot initiate a refresh. Refresh scheduling, credentials, repository configuration, and all
GitHub API calls remain owned by the danielsmith.io cache sidecar. Collection must never be used as
a scheduler.

Lifecycle is exactly `disabled`, `warming`, `fresh`, `stale`, or `unavailable`; completeness is
`complete`, `partial`, or `none`. Failure categories are exactly `configuration`, `internal`,
`invalid_response`, `network`, `not_found`, `rate_limited`, `timeout`, and `upstream`. Only the
fixed `state`, `completeness`, and `category` domains become labels. Repository identities, URLs,
request identifiers, credentials, and upstream error text are rejected by the exact input schema.

Counts are integers from 0 through 50, refresh duration is at most 3,600,000 milliseconds, and
retained age is at most 31,536,000 seconds. Timestamps must be canonical UTC. State/count,
enablement, completeness, timestamps, duration, age, and failure-category relationships are
revalidated and contradictory input fails closed without replacing prior collector output.

A stale snapshot preserves `lastSuccessfulRefreshAt` and derives freshness from the oldest retained
record through `oldestDataFetchedAt` and `retainedDataAgeSeconds`. A failed refresh therefore never
looks like a new success. Warming, unavailable, disabled, and absent telemetry are not success.

## Alerts

Canonical rules are diagnostic warnings gated by both the environment-specific expected recording
rule and the collector's enabled marker. They distinguish expected-but-missing telemetry, stale
retained data, unavailable data, and current bounded refresh failures. They do not page for public
site availability.
