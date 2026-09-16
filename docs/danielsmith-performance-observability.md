# danielsmith.io controlled performance observability

Sugarkube passively consumes the application-owned `PerformanceResultV1` contract introduced by
danielsmith.io revision `26f0745d91f6522e0fd8d618929db74d563d6f07`. The existing visitor-journey scheduler
owns browser execution and writes the sanitized result. This integration does not add a timer, browser runner, analytics service, credential, deployment, or environment mutation.

Run `scripts/daniel_performance_metrics.py` from the existing visitor-journey completion hook. Give
it the result file, the scheduler's fixed environment, and the node-exporter textfile destination:

```console
python3 scripts/daniel_performance_metrics.py \
  --environment staging \
  --result /run/sugarkube/danielsmith-visitor/performance-result-v1.json \
  --output /var/lib/node_exporter/textfile_collector/daniel-performance.prom
```

The collector validates the exact version-one keys and relationships before atomically replacing
the textfile. Missing, malformed, and oversized input replaces prior healthy samples with explicit
collection/document status and no duration series. Thus unsupported application readiness,
interaction latency, and frame measurements display `NO DATA`, never zero or success. Frame
summaries are emitted only for the contract's qualified 120-sample Chromium hardware profile;
software, unknown, fallback, and uncollected runs remain separate and do not fabricate frame data.

Labels are restricted to fixed environment, result-state, renderer-class, renderer-state,
fallback-reason, document-status, and summary-statistic domains. The build info series accepts only
the contract's safe 80-character tag and the selected environment. Exact-key validation rejects
session identifiers, user input, individual events, console errors, arbitrary URLs, raw GPU
strings, headers, addresses, and open-ended environment data. The 90-day Prometheus retention
policy and the normal textfile scrape/missing-data conventions remain unchanged.

The dashboard panels are **Daniel performance result state**, **Daniel application readiness**,
**Daniel interaction latency**, **Daniel renderer and fallback state**, and **Daniel frame time
(qualified hardware only)**. There are deliberately no thresholds or paging alerts. A later,
separately authorized staging rollout must confirm scheduler handoff, scrape freshness, browser
conditions, renderer qualification, and a measured baseline. Production promotion must then repeat
that qualification—especially hardware rendering—before anyone proposes production thresholds.
