---
personas:
  - software
---

# Private aggregate evidence retention

This local-only contract implements [#2782](https://github.com/futuroptimist/sugarkube/issues/2782).
The [store](../../scripts/tokenplace_evidence.py) accepts already aggregated JSON from a reviewed
producer. It does not scrape, query Prometheus, read request logs, contact a relay, run an observer,
or change monitoring configuration. It is not a replacement for an immutable drill plan or its
append-only execution journal. Store only validated aggregates here; keep operational authority
and private rollback coordinates in their existing separate workflow.

## Source contracts and dimensions

The quota vocabulary comes from
[token.place #1771](https://github.com/futuroptimist/token.place/issues/1771) and its
[public quota contract](https://github.com/futuroptimist/token.place/blob/4fdc779858140608edce8adfc49d6a21243fa781/docs/ops/public-quota-telemetry.md).
The consumer follows [#2405](https://github.com/futuroptimist/sugarkube/issues/2405)'s bounded
aggregation and missing-data policy. This change adds no metric, query, dashboard, alert, label,
or collection job, and does not change the existing Prometheus retention policy.

Every record has exactly these fields:

| Field | Contract |
| --- | --- |
| `schema_version` | Integer `1` |
| `environment` | `staging` or `prod`; this names evidence, not an execution target |
| `bucket` | Unix UTC start second, divisible by 300; the five-minute bucket must be closed |
| `coverage` | Exactly `http`, `quota`, `scrape`, `runtime`, each `complete`, `partial` or `unavailable` |
| `http` | Unique rows `[method, status_class, count]`, at most 48 |
| `quota` | Unique rows `[route_class, method, outcome, reason, count]`, at most 480 valid combinations |
| `scrape` | Exactly `samples_max`, `series_added_max`, `duration_ms_max`, `size_bytes_max`, `route_series_max` |
| `runtime` | Exactly `restarts`, `ooms`; reset-aware increases during this bucket |

Methods are `GET`, `POST`, `PUT`, `PATCH`, `DELETE`, `OPTIONS`, `HEAD`, `other`.
Status classes are `1xx`, `2xx`, `3xx`, `4xx`, `5xx`, `other`.
Quota routes are `root`, `public_metadata`, `public_version`, `api_v1`, `api_v2`, `operational`,
`static`, `control_plane`, `other_known`, `unmatched`. Outcomes are `accepted`, `exempt`, `rejected`.
Accepted and exempt outcomes require reason `none`. Rejected outcomes require `hourly_limit`,
`daily_limit`, `other_limit` or `other_rejection`.

The producer must derive quota classes from application-owned endpoint/rule classification,
**before aggregation**, as #1771 does. The store rejects raw paths rather than trying to sanitize
them. Never map the canonical HTTP metric's `other` route label to `unmatched`: it also includes
legitimate routes. HTTP rows deliberately omit routes, preserving method/status totals without
inventing a join between incompatible label vocabularies. Quota rejection counts describe the
public quota metric's 429 decisions, and unmatched counts are sums of its `unmatched` rows;
neither is an inference outcome metric. Metrics scrapes are excluded from the public quota counter.

All aggregate numbers must be finite, nonnegative and at most one trillion. Booleans, strings,
NaN and infinity are rejected. Fractional counts are allowed because Prometheus `increase()` can
extrapolate; they are estimates, not exact request counts. Compute reset-aware increases per
process before summing counters. For shared logical gauges, use the reviewed deduplication from
#2405 rather than summing repeated replica values. Scrape fields are maxima over the bucket for
the reviewed target set, not sums; `route_series_max` counts only reviewed bounded series.
Do not silently replace missing sources with zero or infer an OOM from an HTTP error.

`complete` asserts the reviewed source set was observed throughout the bucket. Omitted HTTP or
quota combinations then mean zero; under `partial` they mean unknown. `unavailable` requires empty
row lists and null summary fields. Complete summary groups require every field to be numeric;
partial groups may use null for missing measurements. A missing bucket always means missing
evidence. These are producer assertions, not independently authenticated measurements. The store
validates structure and bounds, not truthfulness, source health or incident causation.

## Retention, capacity and access

- Logical retention is **24 hours from bucket start**. A bucket expires exactly when
  `bucket <= current_time - 86400`. Old inputs and open/future buckets are rejected. A clock
  reversal that makes a stored bucket appear open stops the operation for operator review.
- There are only 288 fixed slots per environment, 576 total. Each file and accepted input is at
  most **65,536 bytes**. One fixed temporary file is allowed during an atomic replacement; the
  lock is empty. The maximum logical payload on disk is therefore **37,814,272 bytes**
  (`577 * 65536`, about 36.1 MiB), plus filesystem metadata for at most 578 entries. Export is
  at most 37,748,736 bytes (`576 * 65536`). Filesystem allocation overhead is platform-dependent.
- Append, export and prune validate the store and remove expired records. **No background task is
  installed.** An operator adopting the store must run local `prune` at least every five minutes,
  including while ingestion is idle; healthy scheduled cleanup bounds physical retention to
  24 hours plus five minutes. If cleanup stops or the store is corrupt, bytes can remain until
  remediation even though expired records are never exported. Monitor cleanup success locally;
  do not claim expiry ran merely because time passed. This PR performs no scheduling or adoption.
- Use a dedicated directory outside this checkout, owned by the operator, mode `0700`; files
  must be regular, owned by that operator, mode `0600`, with one link. The final store directory
  component and stored entries cannot be symlinks; ancestor components may be symlinks, so use
  a trusted parent path. Hard links, unexpected entries and oversized files fail closed.
  No automatic permission repair occurs.
  The same-UID operator and privileged administrator remain trusted; this is access control,
  not encryption or secure erasure. Use encrypted storage where required and exclude the store
  from sync, backup and source control unless their independent retention/access policy is approved.
- Operations take an exclusive local lock, use directory-relative file operations, and atomically
  replace a bucket after flushing it. A conflicting second version of the same bucket is rejected;
  an identical replay is idempotent. A crash before rename may lose the incoming bucket but leaves
  the earlier version intact; the next locked operation discards the bounded temporary file.
  No historical series, arbitrary filenames, source identities or free-text metadata are added.

## Local use and export

These commands operate only on a reviewed aggregate file and a private local store. They provide
no authority to collect live evidence. The parent directory must already exist. Export writes
validated records as chronological JSON Lines; it creates no export file or retention exception.
The shell's private mode matters when redirecting exported evidence. Any retained export copy
needs its own approved expiry/access policy and must not silently extend the source retention.

```sh
umask 077
python3 scripts/tokenplace_evidence.py append --store "$PRIVATE_AGGREGATE_STORE" < "$REVIEWED_BUCKET"
python3 scripts/tokenplace_evidence.py prune --store "$PRIVATE_AGGREGATE_STORE"
python3 scripts/tokenplace_evidence.py export --store "$PRIVATE_AGGREGATE_STORE" > "$PRIVATE_EXPORT"
```

Input is read only from standard input, bounded before parsing. Unknown fields, duplicate JSON
keys, invalid labels/combinations, duplicate rows and invalid numbers reject the whole incoming
bucket before creating a store. Existing records are all validated before any export. Errors use
one fixed message, never an input, filename or exception body. Invalid input is rejected, not
stored and subsequently redacted. The caller must not archive rejected input as diagnostics.

A schema example (replace only the time with a reviewed closed bucket; this is not live evidence):

```json
{
  "schema_version": 1,
  "environment": "staging",
  "bucket": 1800000000,
  "coverage": {"http": "complete", "quota": "complete", "scrape": "unavailable", "runtime": "complete"},
  "http": [["GET", "2xx", 100], ["GET", "4xx", 2]],
  "quota": [["root", "GET", "exempt", "none", 100], ["unmatched", "GET", "rejected", "hourly_limit", 2]],
  "scrape": {"samples_max": null, "series_added_max": null, "duration_ms_max": null, "size_bytes_max": null, "route_series_max": null},
  "runtime": {"restarts": 0, "ooms": 0}
}
```

For a sanitized postmortem, compare adjacent buckets' status totals, rejected/accepted/exempt
quota counts and rejection reasons, unmatched counts, scrape/cardinality maxima and restart/OOM
increases. Report missing/partial coverage and describe counts as reset-aware estimates; records
do not retain counter-reset history. Bucket resolution, extrapolation,
deduplication, upstream loss and private-copy expiry limit completeness. This cannot reconstruct
individual requests, exact user impact, actor identity or intent. Raw paths, query strings,
addresses, forwarded headers, user agents, limiter keys, request IDs, credentials, ciphertext,
prompts, responses and arbitrary errors are not allowed anywhere in the schema.

## Verification

```sh
pytest -q tests/test_tokenplace_evidence.py
```

Tests cover exact finite domains, all valid combinations and serialization bounds, thousands of
invalid labels, missing-versus-zero semantics, deterministic export, conflicting replay, expiry
boundaries, full slot capacity, both environments, clock reversal, permissions, links, locks,
crash cleanup and atomic replacement failure. They perform no live collection. Adoption of a
producer, cleanup schedule or operational drill is separately authorized work; the repository
contract does not claim that any deployment now retains this evidence.
