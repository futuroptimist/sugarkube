# danielsmith.io controlled-performance observability

Sugarkube passively consumes `PerformanceResultV1`, published by danielsmith.io at
revision `26f0745d91f6522e0fd8d618929db74d563d6f07`. The application owns browser
measurement and exact schema validation. Sugarkube only validates the same finite
contract, translates it to node-exporter textfile metrics, and visualizes it. It
does not collect real-user analytics.

## Schedule and collection ownership

The existing Daniel visitor-journey scheduler owns controlled browser execution.
Its job may write one performance result and then invoke the passive adapter:

```bash
python3 scripts/daniel_performance_metrics.py \
  --environment staging \
  --result /var/lib/sugarkube/danielsmith/performance-result.json \
  --output /var/lib/node_exporter/textfile_collector/daniel-performance.prom
```

Performance collection must not create a second timer or overlap browser runs.
This repository change adds no timer, enables no producer, and makes no staging or
production mutation. Environment qualification must wire the adapter into the
already-authorized visitor job, using its existing cadence, timeout, and single-run
concurrency. A malformed, missing, or oversized input atomically replaces old
samples with `daniel_performance_collection_up 0`; it never leaves a stale healthy
result behind.

## Measurement semantics

The adapter accepts only schema version 1 and the exact application-owned fields.
It distinguishes `completed`, `regression`, and `unavailable`; a regression is a
producer classification against caller-supplied comparison limits, not a Sugarkube
alert threshold. Required readiness and interaction measurements are exported in
seconds. Interaction summaries describe controlled keyboard event-dispatch delay
at the passive listener; they are not paint, presentation, or end-to-end response
latency.

Renderer class (`hardware`, `software`, or `unknown`), renderer state, and fallback
reason are finite labels. Hardware and software results must not be combined when
reviewing a baseline. Optional frame summaries appear only for a valid 120-frame
`controlled_hardware_v1` Chromium run with an active hardware renderer. When a
software renderer, fallback, unsupported environment, or uncollected frame window
is reported, the availability metrics retain that reason while numeric frame-time
series are absent. Grafana therefore shows **NO DATA**, never a fabricated zero.

The dashboards provide these query panels:

- **Daniel performance result state** — `daniel_performance_result_state`;
- **Daniel application-ready duration** — `daniel_performance_application_ready_seconds`;
- **Daniel controlled interaction latency** — `daniel_performance_interaction_latency_seconds`;
- **Daniel renderer and fallback state** — `daniel_performance_renderer_class` and
  `daniel_performance_fallback`;
- **Daniel controlled frame time** — `daniel_performance_frame_time_seconds`, only
  when the application supplied a qualified frame summary.

All queries select the dashboard environment and deliberately avoid `vector(0)` so
missing collection stays visible as **NO DATA**. Existing Prometheus retention and
textfile scrape conventions apply; this integration adds no separate store.

## Privacy and identity boundary

Accepted dimensions are fixed enums for environment, result state, measurement,
renderer class/state, fallback reason, unavailable reason, and summary statistic.
Build identity is limited to `dev`, `staging`, or `prod` plus an 80-character safe
release tag. Exact-key checks reject browser-session identifiers, user input,
individual events, arbitrary URLs, raw renderer strings, raw console errors,
headers, cookies, IP addresses, and open-ended environment values. Payloads larger
than 64 KiB are rejected before decoding.

## Later environment qualification

No production performance threshold or paging alert is established here. A later,
explicitly authorized staging task must verify the immutable application build,
the shared scheduler handoff, textfile freshness, browser profile, renderer
classification, and dashboard population over a measured observation window.
Hardware frame qualification needs actual hardware evidence; software-rendered CI
results cannot substitute for it. Production promotion requires separate approval,
its own baseline, and verification that hardware and software populations remain
separate. Roll back by removing only the performance-adapter invocation from the
visitor job; retain the visitor schedule and existing observability release.
