# Sugarkube blackbox monitoring

This page documents the first runtime slice of Sugarkube public availability monitoring. It describes source configuration only; it is not live deployment evidence. Do not claim any target is deployed or healthy until an operator verifies the rendered resources and public probes on the target cluster.

## Architecture

Flux installs `prometheus-blackbox-exporter` in the internal `monitoring` namespace from the existing `prometheus-community` HelmRepository. Prometheus Operator `Probe` resources also live in `monitoring` and use the existing discovery label `release: kube-prometheus-stack` so kube-prometheus-stack selects them alongside the existing Traefik and cloudflared monitoring resources.

No public Ingress is added for Prometheus, Grafana, Alertmanager, or the blackbox exporter. Prometheus scrapes the exporter through the in-cluster service `prometheus-blackbox-exporter.monitoring.svc.cluster.local:9115`.

## Modules

The exporter is deliberately small:

- `https_2xx`: generic HTTPS GET, follows redirects, requires TLS verification, and expects HTTP 200.
- `https_json_health`: HTTPS GET for `/healthz` and `/livez`, follows redirects, requires TLS verification, expects HTTP 200, and bounds the body assertion to small health-style responses.
- `https_static_content`: HTTPS GET for stable public metadata/static content markers such as DSPACE config, token.place metadata, danielsmith.io runtime metadata, or future static app markers.

## Labels

Every active probe target has bounded labels:

| Label | Allowed values in this slice |
| --- | --- |
| `app` | `dspace`, `tokenplace`, `danielsmith`, `jobbot3000` |
| `environment` | `staging`, `prod` |
| `route` | `root`, `healthz`, `livez`, `config`, `metadata` |
| `criticality` | `critical`, `warning` |

Routes are semantic names, never arbitrary URLs. This keeps query cardinality bounded while preserving enough context for dashboards and alerts.

## Active source targets

Targets are derived from committed Sugarkube app runbooks and values files. Production jobbot3000 is intentionally omitted because the committed production values still use the placeholder host `jobbot3000.example.test` and the runbook says production promotion is blocked until staging is verified and approved.

| App | Environment | Routes |
| --- | --- | --- |
| DSPACE | staging | `/`, `/config.json`, `/healthz`, `/livez` |
| DSPACE | prod | `/`, `/config.json`, `/healthz`, `/livez` |
| token.place | staging | `/`, `/healthz`, `/livez`, `/api/v1/meta` |
| token.place | prod | `/`, `/healthz`, `/livez`, `/api/v1/meta` |
| danielsmith.io | staging | `/`, `/healthz`, `/livez`, `/runtime/github-metrics.json` |
| danielsmith.io | prod | `/`, `/healthz`, `/livez`, `/runtime/github-metrics.json` |
| jobbot3000 | staging | `/`, `/healthz`, `/livez` |

Omitted until the app contracts document stable public paths: danielsmith.io `/resume.pdf`, jobbot3000 tracker subpage, jobbot3000 manifest, and jobbot3000 production.

## PromQL examples

```promql
sum by (app, environment, route) (probe_success)
```

```promql
histogram_quantile(
  0.95,
  sum by (le, app, environment, route) (rate(probe_http_duration_seconds_bucket[5m]))
)
```

```promql
min by (app, environment) (probe_ssl_earliest_cert_expiry - time()) / 86400
```

If `probe_duration_seconds` is preferred for a simple panel:

```promql
avg by (app, environment, route) (probe_duration_seconds)
```

## Troubleshooting

1. Confirm Flux rendered the HelmRelease and values ConfigMap in `monitoring`.
2. Confirm the blackbox exporter Service exists in `monitoring`.
3. Confirm Probe resources have the `release: kube-prometheus-stack` label.
4. Use Prometheus target discovery to check whether each Probe was selected.
5. Compare failures by route: `root` often isolates public routing/TLS, while `healthz` and `livez` isolate app readiness contracts.
6. For Cloudflare or DNS failures, use the relevant app runbook before changing monitoring labels or targets.

## Staging-to-production promotion

Add staging probes first from committed app values and runbooks. Promote production probes only when a real production hostname is committed and the app runbook says production rollout is approved. Placeholder hosts, unresolved launch plans, and private admin endpoints must stay out of active Probe resources.
