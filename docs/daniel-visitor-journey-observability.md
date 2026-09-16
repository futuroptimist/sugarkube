# Daniel visitor-journey observability

Sugarkube consumes the sanitized visitor-journey result owned by
`danielsmith.io`; it does not repeat the browser assertions. The accepted result
contains only `state`, `freshness`, `aggregateDurationMs`, and `failureStage`.
Failure stages are limited to homepage delivery, JavaScript initialization,
essential assets, accessible fallback, résumé PDF, timeout, and producer
interruption.

The staging and production descriptors in
`config/observability/daniel-visitor-journey.json` are deliberately disabled.
They declare a 15-minute cadence, a 60-second timeout, concurrency of one, and
reviewed request quotas, but omit request multiplicity so fail-closed validation
prevents accidental activation. Separately authorized qualification must set a
reviewed multiplicity and enable one environment in a later change.

The metrics adapter distinguishes disabled, unavailable, stale, failed,
recovered, and successful lifecycle states. A disabled or absent producer does
not emit a successful result. Optional immersive-renderer state is a separate
metric and alert; its failure cannot change essential journey success. The
adapter rejects unknown fields, nonfinite values, future timestamps, and failure
stages outside the application vocabulary.

Regenerate and validate the environment dashboards offline with:

```bash
python scripts/generate_observability_dashboards.py --write
python scripts/generate_observability_dashboards.py --check
python scripts/validate_observability_dashboard.py \
  clusters/staging/observability/dashboards/sugarkube-staging-observability.json
python scripts/validate_observability_dashboard.py \
  clusters/prod/observability/dashboards/sugarkube-prod-observability.json
```

These repository declarations do not activate a timer, execute a browser, or
establish staging or production readiness.
