# Public blackbox monitoring

The current blackbox path is a guarded, **staging-only, non-Flux** Helm lifecycle. It installs an internal blackbox exporter and applies exactly 16 Prometheus Operator `Probe` objects. Repository configuration is not evidence that either resource is deployed; deployment and validation are separate, post-merge operator actions.

## Canonical configuration and architecture

- Release: `prometheus-blackbox-exporter` in `monitoring`.
- Chart: `prometheus-community/prometheus-blackbox-exporter` from the official `https://prometheus-community.github.io/helm-charts` repository.
- Pin: `platform/observability/helm/prometheus-blackbox-exporter.version` (`11.15.1`).
- Complete staging values: `clusters/staging/observability/prometheus-blackbox-exporter.values.yaml`.
- Probe render root: `clusters/staging/observability/probes/kustomization.yaml`.
- Lifecycle helper: `scripts/observability_blackbox.sh`, exposed through `just observability-blackbox-*`.

The exporter service is available only as `prometheus-blackbox-exporter.monitoring.svc.cluster.local:9115`. It is a single-replica `ClusterIP` service with no Ingress, NodePort, persistence, credentials, or NetworkPolicy. Prometheus and its Kubernetes service proxy remain LAN/internal-only; this lifecycle creates no public observability access.

The three bounded modules are `https_2xx`, `json_health_2xx`, and `static_content_2xx`. They require verified HTTPS, use finite timeouts, and bound content-check response bodies. The chart creates a ServiceMonitor labeled `release: kube-prometheus-stack`.

## Prerequisites and commands

Before any install or upgrade, select the `sugar-staging` context and confirm that the canonical `kube-prometheus-stack` release, the `Probe` and `ServiceMonitor` CRDs, and the `kube-prometheus-stack-prometheus` service exist in `monitoring`. Helm, kubectl, Python 3, and access to the official chart repository are required.

```bash
just observability-blackbox-render env=staging
just observability-blackbox-install env=staging
just observability-blackbox-upgrade env=staging
just observability-blackbox-status env=staging
just observability-blackbox-verify env=staging
```

`install` is only for an absent exporter release; it fails if the exact release already exists. `upgrade` is only for an existing release; it fails when absent. Both render the pinned chart and Probes first, validate context and cluster identity, run prerequisites, pass the complete values file with `--wait`, and apply Probes only after Helm succeeds. They never reuse live values. `render`, `status`, and `verify` do not mutate the cluster.

Only explicit staging is supported. The deprecated `env=int` alias normalizes to staging. Missing, unknown, `prod`, and `production` are rejected. Production Probe ownership is deliberately absent.

## Exact staging target matrix

| App | Base URL | Route label | Path |
| --- | --- | --- | --- |
| dspace | `https://staging.democratized.space` | `root` | `/` |
| dspace | `https://staging.democratized.space` | `config` | `/config.json` |
| dspace | `https://staging.democratized.space` | `healthz` | `/healthz` |
| dspace | `https://staging.democratized.space` | `livez` | `/livez` |
| tokenplace | `https://staging.token.place` | `root` | `/` |
| tokenplace | `https://staging.token.place` | `healthz` | `/healthz` |
| tokenplace | `https://staging.token.place` | `livez` | `/livez` |
| tokenplace | `https://staging.token.place` | `metadata` | `/api/v1/meta` |
| danielsmith | `https://staging.danielsmith.io` | `root` | `/` |
| danielsmith | `https://staging.danielsmith.io` | `healthz` | `/healthz` |
| danielsmith | `https://staging.danielsmith.io` | `livez` | `/livez` |
| jobbot3000 | `https://staging.jobbot3000.tech` | `root` | `/` |
| jobbot3000 | `https://staging.jobbot3000.tech` | `healthz` | `/healthz` |
| jobbot3000 | `https://staging.jobbot3000.tech` | `livez` | `/livez` |
| jobbot3000 | `https://staging.jobbot3000.tech` | `tracker` | `/tracker` |
| jobbot3000 | `https://staging.jobbot3000.tech` | `manifest` | `/manifest.webmanifest` |

Every Probe has bounded `release`, `app`, `environment`, `route`, and `criticality` labels. Verification checks this exact matrix, eventual Prometheus discovery, `probe_success == 1`, and the duration, HTTP status, DNS lookup, and earliest TLS certificate expiry metric families through the Kubernetes service proxy.

## Rollout and rollback

After merge, an operator—not repository automation—should:

1. select and independently confirm `sugar-staging`;
2. render and review both outputs;
3. use `install` for a fresh release or `upgrade` for an existing release;
4. run `status`, then `verify` through convergence;
5. record deployment evidence separately from the repository change.

For rollback, check out the last known-good pin, values, and Probe directory, render them, then run `observability-blackbox-upgrade env=staging` and verify. There is intentionally no uninstall recipe. If Helm fails, Probes are not applied; repair the cause and retry the correct operation.

## Troubleshooting

- **Missing CRDs or base stack:** install/repair the canonical staging kube-prometheus-stack lifecycle first. Do not install Flux CRDs as a workaround.
- **Exporter not ready:** use `status`, then inspect the Deployment events and pod logs. Keep diagnostic output free of credentials and arbitrary target payloads.
- **TLS, DNS, or HTTP failure:** check the bounded `app` and `route` result, certificate chain/expiry, public DNS resolution, tunnel/application readiness, and expected status or body contract.
- **Absent Prometheus series:** confirm the ServiceMonitor label, Probe labels, exporter service, and Prometheus target discovery. Initial discovery and scrapes are eventually consistent, so `verify` polls for a bounded period.
- **Timeout:** diagnostics intentionally contain only app, environment, route, health, and a redacted error; query sensitive details manually only in an approved operator environment.

## Legacy/Future Flux ownership boundary

`platform/observability/prometheus-blackbox-exporter.yaml` and `monitoring/probes/public-apps.yaml` remain only as clearly marked legacy/future references. They are absent from all active dev, staging, and production Kustomize reconciliation graphs. Future Flux adoption must first retire this manual lifecycle and must never manage the same Helm release or Probe objects simultaneously. Placeholder and production targets must not be copied into the staging lifecycle.
