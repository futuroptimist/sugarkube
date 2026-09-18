# Daniel GitHub-cache collector

Sugarkube consumes the application contract pinned at
`c4d45d96f593d0075096c55ea0a71215350b5ed3`. Both staging and production
producers in `config/observability/danielsmith-github-cache.json` are disabled by
default; collection and alerts remain inactive until a separately reviewed activation.

The collector reads the environment's static `/runtime/github-metrics.json` snapshot.
Serialization and collection never call GitHub. Refresh scheduling, credentials, rate-limit
handling, and all upstream GitHub API calls remain owned by the danielsmith.io cache sidecar.

## Contract

The only label domains derived from the payload are:

- lifecycle `disabled`, `warming`, `fresh`, `stale`, or `unavailable`;
- completeness `complete`, `partial`, or `none`;
- failure category `configuration`, `internal`, `invalid_response`, `network`, `not_found`,
  `rate_limited`, `timeout`, or `upstream`.

Repository identities, URLs, request identifiers, credentials, and upstream error text are never
labels. The adapter rejects unknown fields, invalid identities, non-finite or out-of-range values,
and contradictory state/count/timestamp relationships. Invalid or absent input produces explicit
unavailable collection metadata, never a success.

`lastSuccessfulRefreshAt` advances only after a wholly successful refresh. The collector derives
freshness from that retained last-good timestamp; a partial or failed refresh cannot reset it.
`oldestDataFetchedAt` and `retainedDataAgeSeconds` retain the age of stale fallback data.

## Collection

After separate authorization, provision the descriptor-driven command on exactly one monitored
node per environment:

```bash
python3 scripts/daniel_cache_metrics.py \
  --descriptor config/observability/danielsmith-github-cache.json \
  --environment staging \
  --output /var/lib/node_exporter/textfile_collector/daniel-cache.prom
```

The reviewed five-minute cadence only retrieves the passive application snapshot. It does not
schedule or duplicate application refresh work.

## Alerts

Canonical rules distinguish expected-but-missing collection, stale fallback, unavailable data,
and a current bounded refresh failure. Every alert is gated by the environment-specific
`daniel_cache_monitoring_expected` and `daniel_cache_monitoring_enabled` series, so the default
disabled configuration cannot report success or alert.
