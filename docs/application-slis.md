# Application SLI foundation

`config/observability/application-slis.json` is the machine-readable contract for token.place,
DSPACE, and danielsmith.io. It deliberately separates public HTTP probe health, bounded synthetic
completion, and actual request success. A successful probe says nothing about all real-user
requests, and a synthetic result is not counted as production traffic.

No reviewed numerical objective exists in this repository, so every entry is `unmeasured`; the encrypted-completion synthetic is additionally and explicitly disabled.
Consequently the shared dashboard says **UNMEASURED — NO DATA** for budget and burn rather than
inventing an uptime promise. This change adds recording rules only; it adds no alert, route, page,
probe activation, or producer.

The existing `encrypted_completion_monitoring_enabled` and `encrypted_completion_lifecycle_state` metrics define a disabled synthetic contract; this does not create or activate a producer.

The request recordings use a one-hour window, aggregate replicas, and retain Prometheus's native
counter-reset handling. A reset makes the window `reset_or_incomplete_history`, rather than a usable ratio. The configured 30-second scrape interval must provide at least 120 samples
for every observed source series in that hour, and the latest sample must be no older than 60
seconds. These guards make stale, gapped, or partial history NO DATA. Recordings are also absent
when there is no eligible traffic instead of converting that absence to success or failure.
The `sugarkube:sli_observation_state` recording emits exactly one mutually exclusive state per application, environment, SLI, and signal type. Operators must interpret the states separately:

- a positive denominator with all successes is successful eligible traffic;
- a positive denominator with fewer successes is failed eligible traffic; an absent success
  outcome is conditionally represented as zero only in this state;
- an absent denominator with healthy source telemetry is no eligible traffic;
- absent or stale source telemetry is missing telemetry, not zero traffic;
- less than one hour of samples, a scrape gap, or history lost before a scrape is incomplete history;
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
