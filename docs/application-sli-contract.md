# Application SLI contract

`platform/observability/application-slis.json` is the bounded, machine-readable contract for
token.place, DSPACE, and danielsmith.io. Its validator prevents HTTP probes from being described as
real traffic. Probe health, controlled synthetic completion, and actual instrumented request success
remain separate signals. Missing data is never converted to zero.

No reviewed numerical objective exists in this repository, so every error budget and burn-rate
output is explicitly **NO DATA**. This change adds no alert, page, route, producer, probe activation,
or uptime promise. The request recording rules merely aggregate existing counters across replicas.
They exclude operational endpoints and deliberately return no ratio for no eligible traffic.

The contract's 24-hour view is bounded by the smallest configured environment retention (15 days),
but retention does not prove that 24 hours were observed. A new series, scrape gap, or counter reset
makes the history incomplete until a continuous window is available. Operators must distinguish:

- successful and failed eligible traffic;
- no eligible traffic;
- missing or stale telemetry;
- reset or incomplete history; and
- intentionally disabled monitoring.

The token.place encrypted-completion and Daniel visitor producers remain intentionally disabled.
Their disabled state is not success. Existing DSPACE release-integrity, incident, chat-synthetic,
encrypted-completion, and Daniel visitor rules and panels remain authoritative and unchanged.

Validate locally with:

```bash
python3 scripts/validate_application_slis.py
python3 -m pytest -q tests/test_application_sli_contract.py
```
