# Application SLI foundation

`config/observability/application-slis.json` is the machine-readable contract for token.place,
DSPACE, and danielsmith.io. It deliberately separates public HTTP probe health, bounded synthetic
completion, and actual request success. A successful probe says nothing about all real-user
requests, and a synthetic result is not counted as production traffic.

No reviewed numerical objective exists in this repository, so every entry is `unmeasured`.
Consequently the shared dashboard says **UNMEASURED — NO DATA** for budget and burn rather than
inventing an uptime promise. This change adds recording rules only; it adds no alert, route, page,
probe activation, or producer.

The request recordings use a one-hour window, aggregate replicas, and retain Prometheus's native
counter-reset handling. They are absent when there is no eligible traffic instead of converting
absence to success or failure. Operators must interpret the states separately:

- a positive denominator with all successes is successful eligible traffic;
- a positive denominator with fewer successes is failed eligible traffic;
- an absent denominator with healthy source telemetry is no eligible traffic;
- absent or stale source telemetry is missing telemetry, not zero traffic;
- a reset or less than one hour of samples is incomplete history;
- an expected/enabled value of zero is intentionally disabled monitoring.

Prometheus is configured for at most 90 days of retention, subject to its 100 GB size cap. The
contract therefore rejects longer windows. The one-hour recordings are observation views, not a
claim that 90 complete days are available; restarts, late installation, gaps, resets, and the size
cap can shorten usable history.

Validate with:

```bash
python3 scripts/validate_application_slis.py
pytest -q tests/test_application_sli_contract.py
```
