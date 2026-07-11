# Public blackbox monitoring

This page documents Sugarkube's first runtime observability slice: Prometheus Operator `Probe` resources that ask an in-cluster blackbox exporter to check public application URLs. The manifests are source configuration only; they are not live deployment evidence. Do not claim a target is deployed or healthy until an operator verifies the rendered resources and resulting metrics on a real cluster.

## Architecture

Flux installs `prometheus-blackbox-exporter` in the `monitoring` namespace from the existing `prometheus-community` HelmRepository. The chart is pinned to version `11.15.1`, and the container image is pinned to `quay.io/prometheus/blackbox-exporter:v0.27.0`.

The exporter is internal-only:

- Service type is `ClusterIP`.
- Ingress is disabled.
- The chart's own `ServiceMonitor` is disabled so Prometheus Operator `Probe` resources remain the single target contract.

Prometheus discovers probes through the same label convention used by the existing ServiceMonitors: `release: kube-prometheus-stack`.

## Modules

Sugarkube keeps the initial module set deliberately small:

| Module | Purpose |
| --- | --- |
| `https_2xx` | Generic public HTTPS check. It requires TLS, verifies certificates, follows redirects, and accepts HTTP 200. |
| `https_json_health` | Bounded JSON-style health check for `/healthz`, `/livez`, and safe metadata endpoints. It limits the body to 64 KiB and requires a small success marker. |
| `https_static_content` | Optional static-content check for stable, non-secret public content such as `/config.json`. It limits the body to 128 KiB and checks a small public marker. |

## Labels

Every active target has bounded labels suitable for dashboards and alerts:

- `app`: one of `dspace`, `tokenplace`, `danielsmith`, or `jobbot3000`.
- `environment`: `staging` or `prod` for public runtime probes.
- `route`: a stable route name such as `root`, `healthz`, `livez`, `config`, or `metadata`.
- `criticality`: `critical` for availability gates and `warning` for supporting metadata/content checks.

Never use a full URL, host, request ID, user ID, arbitrary error string, or secret-bearing value as a Prometheus label.

## Active targets

Targets are derived from committed app runbooks and values overlays.

| App | Environment | Routes |
| --- | --- | --- |
| DSPACE | staging | `root`, `config`, `healthz`, `livez` on `https://staging.democratized.space` |
| DSPACE | prod | `root`, `config`, `healthz`, `livez` on `https://democratized.space` |
| token.place | staging | `root`, `healthz`, `livez`, `metadata` on `https://staging.token.place` |
| token.place | prod | `root`, `healthz`, `livez`, `metadata` on `https://token.place` |
| danielsmith.io | staging | `root`, `healthz`, `livez`, `metadata` on `https://staging.danielsmith.io` |
| danielsmith.io | prod | `root`, `healthz`, `livez`, `metadata` on `https://danielsmith.io` |
| jobbot3000 | staging | `root`, `healthz`, `livez` on `https://staging.jobbot3000.tech` |

## Omitted targets and blockers

- jobbot3000 production is omitted because the committed production overlay still uses `jobbot3000.example.test`. Add production probes only after a real production hostname is committed and approved.
- jobbot3000 manifest and dedicated tracker routes are omitted because the Sugarkube runbook currently documents `/`, `/healthz`, and `/livez` only. The root route covers the public tracker page until a stable manifest or route contract is committed.
- danielsmith.io `/resume.pdf` is omitted because the design contract says that root resume path is not yet a verified stable runtime contract. Add a `resume` probe after the runbook/app contract verifies it.

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

For a direct duration series, use:

```promql
avg by (app, environment, route) (probe_duration_seconds)
```

## Troubleshooting

1. Confirm Flux reconciled the HelmRelease and values ConfigMap in `monitoring`.
2. Confirm the exporter Service exists and is cluster-internal.
3. Confirm Probe resources carry `release: kube-prometheus-stack`.
4. In Prometheus, filter `probe_success{app="tokenplace", environment="staging"}` to isolate app/environment issues.
5. Compare root failures with health failures: root-only failures often indicate static routing/content issues, while health failures indicate the app container or upstream runtime is unhealthy.
6. Check Cloudflare DNS and Tunnel routing separately from Kubernetes Ingress; public blackbox probes intentionally exercise the full outside-in path.

## Staging-to-production promotion

Use staging probes to establish baseline success and latency before adding or tightening production alerts. Promotion evidence should cite live Prometheus metrics or `kubectl` output from the target cluster. This source repository only defines desired monitoring configuration; it is not evidence that Prometheus, Grafana, Alertmanager, the exporter, or any target is currently deployed.
