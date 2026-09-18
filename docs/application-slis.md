# Application SLI foundation

The machine-readable contract is
[`config/observability/application-slis.json`](../config/observability/application-slis.json).
It separates **HTTP probe health**, **synthetic completion**, and **actual request success**. An
in-cluster probe describes only its configured endpoint and vantage point; it never represents all
real-user requests. Synthetic DSPACE chat, token.place encrypted completion, and Daniel visitor
results likewise remain separate from request counters.

Every objective is currently `null` (`unmeasured`) because no reviewed numerical SLO exists in the
repository. The dashboard therefore shows `UNMEASURED — NO DATA` for budget and burn rather than
inventing an uptime promise. No alert, page, or Alertmanager route is added by this slice.

The request recordings use `increase` over five minutes, aggregate replicas before division, and
do not use a zero fallback. Consequently successful eligible traffic, failed eligible traffic, and
no eligible traffic remain distinct; absent or stale telemetry stays `NO DATA` rather than becoming
a false success or failure. `increase` tolerates an observed counter reset, but a new series without
enough samples remains incomplete history. Synthetic producers retain their existing explicit
disabled, unavailable/stale, failure, success, and recovery states.

Prometheus is configured for 90 days of time retention and a 100 GB size cap. Either cap may remove
samples first, and newly deployed series have less history. The five-minute request views and
latest-result synthetic views therefore make no claim about a full error-budget window. Revisit
objectives and longer windows only through a separately reviewed contract after retained production
evidence exists.
