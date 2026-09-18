# Daniel GitHub-cache collector contract

Sugarkube consumes the passive cache telemetry introduced by danielsmith.io revision
`c4d45d96f593d0075096c55ea0a71215350b5ed3`. The reviewed descriptor is
`config/observability/danielsmith-github-cache.json`. Both staging and production producers are
pinned to a 15-minute cadence and a 10-second transport timeout, and both remain disabled until a
separate rollout explicitly authorizes them.

## Application-owned boundary

The application owns repository configuration, credentials, GitHub API requests, refresh scheduling,
last-good retention, and publication of `/runtime/github-metrics.json`. Sugarkube does not duplicate
that refresh logic. Its collector performs one bounded HTTP read of the already-published static
snapshot only when its descriptor is enabled. Reading that file does not initiate a GitHub API call;
a disabled producer performs no network I/O at all.

The source lifecycle vocabulary is exactly `disabled`, `warming`, `fresh`, `stale`, and
`unavailable`. Completeness is exactly `complete`, `partial`, or `none`. Refresh failure categories
are exactly `configuration`, `internal`, `invalid_response`, `network`, `not_found`, `rate_limited`,
`timeout`, and `upstream`. No repository identity, URL, request identifier, credential, or arbitrary
upstream error becomes a label. The canonical application metrics use only the bounded `state`,
`completeness`, and `category` dimensions.

The adapter revalidates the schema identity; canonical UTC timestamps; lifecycle/count
relationships; repository counts (0 through 50); refresh duration (at most 3,600,000 milliseconds);
and retained-data age (at most 31,536,000 seconds). It rejects duplicate JSON keys, redirects,
oversized documents, unknown fields, unbounded labels, future timestamps, and contradictory state.
Malformed or missing input publishes only bounded transport health and never synthesizes fresh,
complete, or successful application telemetry.

`lastSuccessfulRefreshAt` advances only after a completely successful refresh. A stale fallback
therefore preserves that timestamp, the oldest retained record timestamp, and its true retained-data
age. Partial failure and `rate_limited` remain visible through fixed categories. A later successful
snapshot naturally clears every failure category and represents recovery without rewriting history.

## Transport and provisioning

The collector uses node exporter's existing textfile transport. An authorized operator installs the
reviewed script and schedules this command on one monitored node per environment:

```bash
python3 /usr/local/libexec/sugarkube/daniel_cache_metrics.py \
  --environment staging \
  --output /var/lib/node_exporter/textfile_collector/daniel-cache.prom
```

Use `--environment prod` for production. The descriptor supplies the only accepted URL, so callers
cannot redirect collection to an arbitrary endpoint. Output is atomically replaced with mode `0644`.
This repository does not install the script, create a timer, modify credentials, or perform a live
rollout.

The Helm rules overlay provisions structurally equivalent staging and production rules. Its
`daniel_github_cache_monitoring_expected` recording rule is `vector(0)` in both environments, so the
rules stay inactive until separately authorized. The rules distinguish expected-but-missing
transport, failed validation/transport, stale retained data, unavailable data, and current bounded
refresh failures. A disabled producer cannot appear successful.

## Alerts

All cache alerts are warning diagnostics and do not change existing Alertmanager routing. They fall
through to the existing null receiver unless a future, separately reviewed routing change says
otherwise. Before activation, validate the descriptor quota and offline Helm render. After an
authorized deployment, verify the textfile timestamp, node-exporter scrape, lifecycle one-hot
series, oldest-data age, last-success timestamp, and bounded categories. Do not infer application
availability from cache health.
