# Staging blackbox observability operations

The current blackbox lifecycle is a guarded, **non-Flux and staging-only** Helm release plus a canonical set of Prometheus Operator `Probe` objects. It runs entirely inside the cluster: the exporter, Prometheus service, and ServiceMonitor are `ClusterIP` resources; this lifecycle creates no Ingress, NodePort, public observability endpoint, credentials, persistence, or NetworkPolicy.

Repository configuration is not evidence of a live deployment. Installation and live validation are separate, explicit post-merge operator actions.

## Canonical sources and ownership

- Release: `prometheus-blackbox-exporter` in `monitoring`.
- Chart: `prometheus-community/prometheus-blackbox-exporter` from `https://prometheus-community.github.io/helm-charts`.
- Version: `platform/observability/helm/prometheus-blackbox-exporter.version` (`11.15.1`).
- Complete staging values: `clusters/staging/observability/prometheus-blackbox-exporter.values.yaml`.
- Staging Probes and deterministic render entrypoint: `clusters/staging/observability/probes/`.
- Guarded helper: `scripts/observability_blackbox.sh`, exposed through `just observability-blackbox-*`.

The exporter has one replica and the bounded `https_2xx`, `json_health_2xx`, and `static_content_2xx` modules. HTTPS validation remains enabled, probe timeouts are finite, and content checks cap response bodies at 1 MiB.

`platform/observability/prometheus-blackbox-exporter.yaml` and `monitoring/probes/` are **LEGACY/FUTURE ONLY** references. They are excluded from all active dev, staging, and production Kustomize graphs. A future Flux adoption must first retire this manual lifecycle; Flux and manual Helm must never manage the same release or Probe names simultaneously.

## Prerequisites and commands

Use a staging kubeconfig with current context `sugar-staging`, a repository-valid staging cluster identity, and installed `helm`, `kubectl`, `python3`, and `just`. The canonical `kube-prometheus-stack` release, `Probe` and `ServiceMonitor` CRDs, and `kube-prometheus-stack-prometheus` service must exist before installation or upgrade. Chart rendering requires access to the official Helm repository.

```bash
just observability-blackbox-render env=staging
just observability-blackbox-install env=staging
just observability-blackbox-upgrade env=staging
just observability-blackbox-status env=staging
just observability-blackbox-verify env=staging
```

`install` is only for an absent exporter release; `upgrade` requires it to exist. Both render the chart and Probe set first, pass the complete committed values file without `--reuse-values`, wait up to the Pi-appropriate timeout, and apply Probes only after Helm succeeds. Status and verify are read-only. The deprecated `env=int` alias resolves to staging; missing, unknown, `prod`, and `production` are rejected. There is deliberately no uninstall or production command.

## Exact staging target matrix

| App label | HTTPS base | Routes (path → route label) |
| --- | --- | --- |
| `dspace` | `https://staging.democratized.space` | `/` → `root`; `/config.json` → `config`; `/healthz` → `healthz`; `/livez` → `livez` |
| `tokenplace` | `https://staging.token.place` | `/` → `root`; `/healthz` → `healthz`; `/livez` → `livez`; `/api/v1/meta` → `metadata` |
| `danielsmith` | `https://staging.danielsmith.io` | `/` → `root`; `/healthz` → `healthz`; `/livez` → `livez` |
| `jobbot3000` | `https://staging.jobbot3000.tech` | `/` → `root`; `/healthz` → `healthz`; `/livez` → `livez`; `/tracker` → `tracker`; `/manifest.webmanifest` → `manifest` |

Exactly 16 Probes carry `release: kube-prometheus-stack` plus bounded `app`, `environment: staging`, `route`, and `criticality` labels. No production or placeholder target belongs to this lifecycle.

## Post-merge rollout and validation

1. Select and independently confirm the `sugar-staging` context and cluster identity.
2. Review `just observability-blackbox-render env=staging`; do not apply that output manually.
3. Use `install` for a fresh release or `upgrade` for an existing release.
4. Run `status`, then `verify`. Verification uses the Kubernetes Prometheus service proxy, polls a bounded number of times for eventual discovery, and requires all 16 `probe_success` values to be `1` plus duration, HTTP status, DNS lookup, and TLS certificate-expiry series.
5. Record rollout evidence separately from the repository change.

No live rollout is performed by repository tests or by merging configuration.

## Troubleshooting

- **Missing CRDs/base stack/service:** install or repair the canonical stack first. Never apply Flux CRDs or the legacy manifest as a workaround.
- **Exporter not ready:** inspect the Deployment and pods with `status`; resolve image pull, resource, or scheduling problems.
- **Failed probe:** use the bounded `app` and `route` labels to identify its owner. DNS failures indicate resolver/tunnel reachability; TLS failures require a valid certificate chain and hostname; HTTP/body failures require the documented route contract. Do not disable TLS verification.
- **Absent series:** allow initial Operator discovery and scrapes to converge, then check the Probe label, ServiceMonitor `release` label, exporter service, and Prometheus Operator logs. Verification never assumes a global target count.
- **Privacy:** helper failures intentionally omit target URLs, response bodies, headers, credentials, raw Prometheus payloads, and unrestricted errors.

## Rollback

Identify the prior exporter Helm revision, roll it back with the same timeout, restore the matching committed version/values, reapply the prior canonical staging Probe render, and verify:

```bash
helm -n monitoring history prometheus-blackbox-exporter
helm -n monitoring rollback prometheus-blackbox-exporter <prior-revision> --wait --timeout 20m
kubectl apply -k clusters/staging/observability/probes
just observability-blackbox-verify env=staging
```

Rollback is an explicit live operator procedure, not a repository test. Never use `--reuse-values`, and never introduce parallel Flux ownership during rollback.
