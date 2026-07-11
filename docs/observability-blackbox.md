# Public blackbox monitoring

This slice adds Prometheus Operator `Probe` resources that ask the in-cluster
`prometheus-blackbox-exporter` Service to check public application URLs from the
monitoring namespace. It is source configuration only: a successful Kustomize
build or Flux reconciliation does not prove the probes are live until an operator
checks the running cluster and Prometheus target state.

## Architecture

- Flux installs `prometheus-blackbox-exporter` in the `monitoring` namespace from
  the pinned `prometheus-community/prometheus-blackbox-exporter` chart.
- kube-prometheus-stack discovers `Probe` objects carrying
  `release: kube-prometheus-stack`.
- The exporter has no public Ingress. Prometheus, Grafana, Alertmanager, and the
  exporter remain internal services.
- Public targets are derived from committed app runbooks and values overlays.

## Modules

- `http_2xx`: HTTPS GET, redirects enabled, TLS verification required, status
  `200` only.
- `http_json_health`: HTTPS GET for `/healthz` and `/livez`, status `200`, TLS
  verification, and a bounded JSON-body assertion for common health fields.
- `http_static_content`: optional HTTPS GET with a bounded non-secret marker
  check. It is installed for future use but is not required by the active probe
  list.

## Label contract

Every active probe target has bounded labels:

- `app`: one of `dspace`, `tokenplace`, `danielsmith`, `jobbot3000`.
- `environment`: `staging` or `prod` for this public runtime slice.
- `route`: bounded route names such as `root`, `healthz`, `livez`, `config`, or
  `metadata`; raw URLs are never used as label values.
- `criticality`: `critical` for core public availability and `warning` for
  metadata/diagnostics checks.

## Active targets

| App | Environment | Routes |
| --- | --- | --- |
| DSPACE | staging `https://staging.democratized.space` | `root`, `config`, `healthz`, `livez` |
| DSPACE | prod `https://democratized.space` | `root`, `config`, `healthz`, `livez` |
| token.place | staging `https://staging.token.place` | `root`, `healthz`, `livez`, `metadata` (`/api/v1/meta`), `metadata` (`/relay/diagnostics`) |
| token.place | prod `https://token.place` | `root`, `healthz`, `livez`, `metadata` (`/api/v1/meta`), `metadata` (`/relay/diagnostics`) |
| danielsmith.io | staging `https://staging.danielsmith.io` | `root`, `healthz`, `livez`, `metadata` (`/runtime/github-metrics.json`) |
| danielsmith.io | prod `https://danielsmith.io` | `root`, `healthz`, `livez`, `metadata` (`/runtime/github-metrics.json`) |
| jobbot3000 | staging `https://staging.jobbot3000.tech` | `root`, `healthz`, `livez` |

## Omitted targets and blockers

- jobbot3000 production is omitted because the committed production overlay still
  uses the placeholder `jobbot3000.example.test` host. Add production probes only
  after the app runbook and values contain a real production hostname.
- jobbot3000 tracker and manifest routes are omitted until a committed runbook or
  app configuration declares stable public paths for them.
- danielsmith.io `/resume.pdf` is omitted until the stable root resume contract is
  implemented and documented as required public behavior.
- No dev public probes are active because committed dev values do not provide real
  public app hostnames for this slice.

## PromQL examples

```promql
sum by (app, environment, route) (probe_success)
```

```promql
histogram_quantile(
  0.95,
  sum by (le, app, environment, route) (rate(probe_duration_seconds_bucket[5m]))
)
```

```promql
min by (app, environment) (probe_ssl_earliest_cert_expiry - time()) / 86400
```

## Troubleshooting

1. Confirm Flux rendered the HelmRelease and values ConfigMap in `monitoring`.
2. Confirm `kubectl -n monitoring get svc prometheus-blackbox-exporter` exists.
3. Confirm the `Probe` objects have `release: kube-prometheus-stack`.
4. In Prometheus, inspect targets for `probe/monitoring/<probe-name>` and compare
   failing labels with the table above.
5. Use app runbooks for ownership: Sugarkube owns the probe list and platform
   stack; app repositories own endpoint semantics and response bodies.

## Staging-to-production promotion

Promotion evidence must separate source configuration from live deployment:

- Source configuration: committed runbooks, values overlays, HelmRelease pins, and
  Probe manifests.
- Live evidence: Prometheus target health, `probe_success`, TLS expiry metrics,
  app rollout status, and explicit curl/jq checks captured after deployment.

Do not claim a service is deployed or healthy from this repository change alone.
