# Daniel GitHub-cache collector contract

Sugarkube consumes the application-owned cache telemetry introduced at immutable
`danielsmith.io` revision `c4d45d96f593d0075096c55ea0a71215350b5ed3`.
Both staging and production descriptors are disabled by default. Enabling collection or alerts is
a separate rollout decision.

## Ownership and transport

The generic collection job may download `/runtime/github-metrics.json` and pass that existing file
to `scripts/danielsmith_github_cache_metrics.py`. The adapter accepts a local file only: it has no
HTTP or GitHub client and cannot initiate an upstream request. Application refresh scheduling,
credentials, GitHub API calls, retention, and snapshot publication remain application-owned.
Collection must never be used to trigger a refresh.

The adapter reads only the top-level `cache` snapshot. It rejects malformed or contradictory data
before atomically replacing its textfile-collector output. Repository keys, identities, URLs,
request identifiers, credentials, and upstream error text are neither labels nor output. The only
variable labels are the fixed `state`, `completeness`, and `category` domains, plus the bounded
descriptor identity (`application`, `environment`, and `name`).

## Exact contract

Lifecycle values are `disabled`, `warming`, `fresh`, `stale`, and `unavailable`. Completeness is
`complete`, `partial`, or `none`. Failure categories are exactly `configuration`, `internal`,
`invalid_response`, `network`, `not_found`, `rate_limited`, `timeout`, and `upstream`.

Counts are integers from 0 through 50, refresh duration is at most 3,600,000 milliseconds, retained
age is at most 31,536,000 seconds, and timestamps must be canonical UTC ISO timestamps. A failed
refresh cannot advance `lastSuccessfulRefreshAt` or the oldest retained record. Consequently,
`daniel_github_cache_last_good_age_seconds` uses the oldest retained-data timestamp and stale
fallback cannot appear fresher merely because a refresh failed.

Disabled collection emits only `daniel_github_cache_monitoring_enabled 0`; missing or disabled
application telemetry is never synthesized as success. Enabled collection preserves all one-hot
lifecycle and completeness series, all fixed failure-category series, timestamps, age, duration,
and configured/successful/failed/retained counts.

## Alerts

Canonical rules remain inactive while `daniel_github_cache_monitoring_expected` is zero. After an
explicit activation, separate warnings distinguish an absent collector result, stale retained data,
unavailable data, and a current bounded refresh failure. An intentionally disabled producer does
not alert.

Validate the offline integration without cluster access:

```bash
python3 -m pytest -q tests/test_danielsmith_github_cache_observability.py
python3 -m pytest -q tests/test_validate_probe_quotas.py
scripts/observability_helm.sh render env=staging
scripts/observability_helm.sh render env=prod
```

The final two commands need the repository's pinned Helm tooling and network-accessible chart
repository. Rendering does not authorize installation.
