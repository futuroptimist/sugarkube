# Public blackbox monitoring

Sugarkube now defines the first Flux-managed runtime slice for public endpoint monitoring. The stack stays internal: Prometheus, Grafana, Alertmanager, and the blackbox exporter are ClusterIP-only resources in `monitoring`; no public ingress is added.

## Architecture

- `platform/observability/prometheus-blackbox-exporter.yaml` installs the pinned `prometheus-community/prometheus-blackbox-exporter` chart at version `11.15.1`.
- `platform/observability/prometheus-blackbox-exporter.yaml` embeds the values ConfigMap with three deliberately small modules: generic HTTPS 2xx, bounded JSON health, and static content.
- `monitoring/probes/public-apps.yaml` defines Prometheus Operator `Probe` resources selected by `release: kube-prometheus-stack`.

## Labels and ownership

Every probe target exports bounded labels: `app`, `environment`, `route`, and `criticality`. App labels are exactly `dspace`, `tokenplace`, `danielsmith`, and `jobbot3000`; route labels use names such as `root`, `healthz`, `livez`, `config`, `metadata`, `tracker`, and `manifest` instead of arbitrary URLs.

App owners own endpoint semantics and public contracts. Sugarkube owns the blackbox exporter, Probe resources, label taxonomy, and promotion runbook. Source configuration in this repository is not live deployment evidence; live evidence requires a later cluster check after Flux reconciliation.

## Active targets

| App | Environment | Routes |
| --- | --- | --- |
| dspace | staging `https://staging.democratized.space` | `root`, `config`, `healthz`, `livez` |
| dspace | prod `https://democratized.space` | `root`, `config`, `healthz`, `livez` |
| tokenplace | staging `https://staging.token.place` | `root`, `healthz`, `livez`, `metadata` (`/api/v1/meta`) |
| tokenplace | prod `https://token.place` | `root`, `healthz`, `livez`, `metadata` (`/api/v1/meta`) |
| danielsmith | staging `https://staging.danielsmith.io` | `root`, `healthz`, `livez` |
| danielsmith | prod `https://danielsmith.io` | `root`, `healthz`, `livez` |
| jobbot3000 | staging `https://staging.jobbot3000.tech` | `root`, `healthz`, `livez`, `tracker`, `manifest` |

## Omitted targets

- jobbot3000 production is omitted because the committed production overlay still uses `jobbot3000.example.test`, which is a placeholder and must never be probed as an active public target.
- danielsmith `/resume.pdf` is omitted because the stable root resume contract is not yet documented as available; the design keeps it future-gated.
- No `environment=dev` targets are included. The shared monitoring matrix contains staging/prod targets and is rendered through whichever `clusters/<env>` Flux profile selects the shared monitoring base, so a dev build may still render Probe objects; the omission means those objects must not probe dev routes or carry `environment=dev`.

## PromQL examples

```promql
sum by (app, environment, route) (probe_success)
```

```promql
histogram_quantile(0.95, sum by (le, app, environment, route) (rate(probe_duration_seconds_bucket[5m])))
```

```promql
min by (app, environment) (probe_ssl_earliest_cert_expiry - time()) / 86400
```

## Troubleshooting

1. Confirm the Probe exists: `kubectl -n monitoring get probe`.
2. Confirm Prometheus discovered it by filtering on `app`, `environment`, and `route` in the Prometheus UI.
3. Run the same target manually from an operator machine with `curl -fsS` before declaring an application outage.
4. Check DNS and Cloudflare Tunnel health when all routes for one host fail together.
5. Check app rollout and ingress when only one route or one app fails.

## Staging-to-production promotion

Add or promote production probes only after the hostname is committed in app values/runbooks, resolves publicly, returns the expected status/body, and has live evidence outside this repository. Do not add placeholders such as `example.test`, `REPLACE`, or localhost targets.
