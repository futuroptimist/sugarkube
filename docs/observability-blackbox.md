# Staging blackbox monitoring

The supported deployment path is a guarded, non-Flux Helm lifecycle for staging only. It installs `prometheus-community/prometheus-blackbox-exporter` `11.15.1` as release `prometheus-blackbox-exporter` in `monitoring`, then applies exactly 16 staging `Probe` objects. Prometheus, the exporter, and Grafana remain LAN/internal-only; this lifecycle creates no public Ingress, NodePort, DNS, credentials, persistence, or NetworkPolicy.

Repository configuration is not evidence of a live deployment. Installation and live validation are a separate, deliberate post-merge operator action.

## Canonical ownership

- Pin: `platform/observability/helm/prometheus-blackbox-exporter.version`
- Complete staging values: `clusters/staging/observability/prometheus-blackbox-exporter.values.yaml`
- Probe render entrypoint: `clusters/staging/observability/probes/kustomization.yaml`
- Lifecycle helper: `scripts/observability_blackbox.sh`

The retained `platform/observability/prometheus-blackbox-exporter.yaml` and `monitoring/probes/public-apps.yaml` are **LEGACY/FUTURE ONLY** references and are absent from active Kustomize graphs. A future Flux migration must first transfer ownership: Flux and this lifecycle must never manage the same Helm release or Probe names simultaneously.

## Prerequisites and commands

Use the `sugar-staging` context on a cluster whose node identity labels assert staging. The canonical `kube-prometheus-stack` release, its Prometheus service, Helm, kubectl, Python 3, and the `Probe` and `ServiceMonitor` CRDs must exist.

```bash
just observability-blackbox-render env=staging
just observability-blackbox-install env=staging
just observability-blackbox-upgrade env=staging
just observability-blackbox-status env=staging
just observability-blackbox-verify env=staging
```

`install` is only for an absent exporter release; it fails if the exact release exists. `upgrade` is only for an existing release and supplies the complete committed values again (never `--reuse-values`). Both render the chart and Probes, validate context, identity, base stack, CRDs, and Prometheus service, wait for Helm, and apply Probes only after Helm succeeds. `status` and `verify` are strictly read-only. Production, missing, and unknown environments are rejected; `int` remains a deprecated alias for staging.

## Exact staging target matrix

| App label | HTTPS origin | Routes (path → label) |
| --- | --- | --- |
| `dspace` | `https://staging.democratized.space` | `/` → `root`; `/config.json` → `config`; `/healthz` → `healthz`; `/livez` → `livez` |
| `tokenplace` | `https://staging.token.place` | `/` → `root`; `/healthz` → `healthz`; `/livez` → `livez`; `/api/v1/meta` → `metadata` |
| `danielsmith` | `https://staging.danielsmith.io` | `/` → `root`; `/healthz` → `healthz`; `/livez` → `livez` |
| `jobbot3000` | `https://staging.jobbot3000.tech` | `/` → `root`; `/healthz` → `healthz`; `/livez` → `livez`; `/tracker` → `tracker`; `/manifest.webmanifest` → `manifest` |

Each Probe carries only the bounded `release`, `app`, `environment`, `route`, and `criticality` taxonomy. HTTPS certificate verification is enabled. Health/content modules have finite timeouts and bounded response bodies.

## Verification and troubleshooting

Verification uses the Kubernetes API service proxy to internal Prometheus. It checks exporter readiness, ClusterIP-only exposure, ServiceMonitor selection, the exact Probe matrix, discovery, `probe_success == 1`, and the duration, HTTP status, DNS lookup, and earliest TLS certificate expiry metric families. Discovery and initial scrapes use bounded polling; diagnostics expose only app, environment, route, health, and a redacted error.

Useful bounded PromQL includes `sum by (app, environment, route) (probe_success)`
and `avg by (app, environment, route) (probe_duration_seconds)`.

- **Missing CRDs:** install/repair the canonical base stack; confirm `probes.monitoring.coreos.com` and `servicemonitors.monitoring.coreos.com` before retrying.
- **Failed probes:** use the bounded app/route diagnostic, then inspect that application's rollout. Do not copy raw Prometheus target payloads into tickets.
- **TLS, DNS, or HTTP failure:** validate the public certificate chain, authoritative DNS, tunnel/ingress health, and expected route status/body from an operator machine.
- **Absent Prometheus series:** confirm the Probe and ServiceMonitor carry `release: kube-prometheus-stack`, then allow the bounded discovery interval to converge.

## Rollback and post-merge rollout

For a bad upgrade, restore the prior known-good repository values/pin in a reviewed commit, then run `just observability-blackbox-upgrade env=staging`; do not use reused values or add an uninstall recipe. If Helm itself reports a failed revision, inspect `helm history` and use an explicitly reviewed Helm rollback only from the staging context, then re-run upgrade so live state again matches the repository.

After merge, an authorized operator should select `sugar-staging`, confirm cluster identity and base-stack health, run render, choose install or upgrade from the exact release state, run status, and finally run verify. Save only bounded command results as rollout evidence. This repository task does not perform that rollout and never proves it occurred.
