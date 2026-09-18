# Application SLI contract

`config/observability/application-slis.json` is the machine-readable source for this first,
non-alerting SLI slice. Its entries state the user journey, signal class, existing data source,
numerator, denominator, exclusions, and observation window. The three signal classes are deliberately
separate: public HTTP probe health proves reachability, synthetic completion proves only its bounded
scripted journey, and actual request success describes eligible server-observed requests. A probe is
never evidence for all real-user requests.

No reviewed numerical objective exists in this repository. Every entry therefore has a null objective
and the explicit `unmeasured` state. Grafana shows **NO DATA — objective unmeasured** rather than a
fabricated budget or burn rate, and this change adds no alerts, paging, or Alertmanager routes.

The request recording rules aggregate across replicas before comparing successful and eligible
traffic. They preserve the distinctions between successful eligible traffic, failed eligible traffic,
no eligible traffic, absent/stale telemetry, reset or incomplete history, and intentionally disabled
monitoring. `increase()` handles ordinary counter resets, while the reset state warns operators not to
interpret the available slice as an uninterrupted history. Synthetic producers retain their existing
disabled and freshness semantics; this slice neither activates nor duplicates them.

Prometheus is configured for at most 90 days of retained history and a size cap that may shorten that
period. The contract validator rejects longer windows. Its current windows are intentionally short,
but a configured window still does not prove that a newly started or reset series contains that much
observed history. Operators must treat reset/incomplete and missing/stale states as unavailable, not
as zero errors or zero traffic.

Validate the contract with:

```bash
python3 scripts/validate_application_slis.py
```
