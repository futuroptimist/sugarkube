# Staging blackbox monitoring

Public-route monitoring has a guarded, **staging-only, non-Flux** lifecycle. The
exporter, Prometheus, and their administrative interfaces remain LAN/internal
only. The exporter is a `ClusterIP` service; this work adds no Ingress,
NodePort, public DNS, router rule, credential, or persistence. The lifecycle
owns one staging-only NetworkPolicy that permits only the canonical
`kube-prometheus-stack` Prometheus pods to reach only the canonical exporter
pods on TCP 9115. The policy selects the exporter and isolates only its ingress;
it does not select Prometheus or affect Prometheus DNS or any other egress. The
observed live baseline had no monitoring default-deny policy or
`allow-monitoring-ingress` policy, so this lifecycle does not assume either one
exists.

## Canonical sources

- Chart: `prometheus-community/prometheus-blackbox-exporter` from the official
  `https://prometheus-community.github.io/helm-charts` repository.
- Exact chart version: `platform/observability/helm/prometheus-blackbox-exporter.version`
  (`11.15.1`).
- Complete staging values:
  `clusters/staging/observability/prometheus-blackbox-exporter.values.yaml`.
- Lifecycle-owned Probes and deterministic Kustomize entrypoint:
  `clusters/staging/observability/probes/`.
- Lifecycle-owned NetworkPolicy and deterministic Kustomize entrypoint:
  `clusters/staging/observability/network-policies/`; the canonical manifest is
  `prometheus-to-blackbox-exporter.yaml`.
- Helper: `scripts/observability_blackbox.sh`, exposed by
  `just observability-blackbox-*`.

Repository configuration is not evidence that these resources are deployed.
Live evidence comes only from the separate post-merge rollout and validation.

## Prerequisites and commands

The canonical `kube-prometheus-stack` Helm release, its `Probe` and
`ServiceMonitor` CRDs, and its Prometheus service must already exist in
`monitoring`. Select a kubeconfig whose current context is exactly
`sugar-staging`; the helper also runs the repository cluster-identity assertion.
Install `helm`, `kubectl`, `python3`, `ruby` (with Psych), and `just`, and ensure chart-repository
access is available.

```bash
just observability-blackbox-render env=staging
just observability-blackbox-install env=staging
just observability-blackbox-upgrade env=staging
just observability-blackbox-status env=staging
just observability-blackbox-verify env=staging
```

Render, status, and verify are read-only. Status displays the exact owned
NetworkPolicy. Install is only for an absent exporter release; upgrade requires
it to exist. Both render the pinned chart, policy, and Probes first, pass the
complete committed values on every Helm operation, and wait up to the
Pi-appropriate timeout. Only after Helm succeeds, they apply the policy, delete
the eleven explicit legacy production Probe names using `--ignore-not-found`,
then apply the rendered staging Probes. A Helm failure makes no policy or Probe
mutation; a policy apply failure prevents both Probe operations. No selector
pruning or staging Probe deletion is used. Neither uses
`--reuse-values`. Missing environments and production are rejected;
`env=int` remains a deprecated alias for staging.

## Exact staging matrix

| App | Base URL | Routes |
| --- | --- | --- |
| DSPACE (`dspace`) | `https://staging.democratized.space` | `/` (`root`), `/config.json` (`config`), `/healthz` (`healthz`), `/livez` (`livez`) |
| token.place (`tokenplace`) | `https://staging.token.place` | `/` (`root`), `/healthz` (`healthz`), `/livez` (`livez`), `/api/v1/meta` (`metadata`) |
| danielsmith.io (`danielsmith`) | `https://staging.danielsmith.io` | `/` (`root`), `/healthz` (`healthz`), `/livez` (`livez`) |
| jobbot3000 | `https://staging.jobbot3000.tech` | `/` (`root`), `/healthz` (`healthz`), `/livez` (`livez`), `/tracker` (`tracker`), `/manifest.webmanifest` (`manifest`) |

These are exactly 16 Probes. Labels are bounded to `release`, `app`,
`environment: staging`, `route`, and `criticality`. Verification uses the
Prometheus Kubernetes service proxy and bounded polling to prove the exact
app/route target matrix, `probe_success == 1`, and the duration, HTTP status,
DNS lookup, and earliest TLS certificate-expiry metric families. It never logs
raw target payloads or URLs; terminal diagnostics contain bounded labels and
health/series states only. Before polling Prometheus, verification fails closed
unless the deployed policy selects exactly the exporter pods and has one
ingress peer selecting exactly the Prometheus pods, one rule, the sole
`Ingress` policy type, and exactly TCP 9115; broad or additional behavior is
rejected.
The exact policy has a single `Ingress` type and no `egress` field. The former
policy selected Prometheus for egress, which caused Kubernetes to isolate all
Prometheus egress on the observed baseline while allowing only exporter TCP
9115. That blocked DNS and put every scrape path at risk. Selecting only the
exporter for ingress avoids that failure mode: Prometheus DNS and all other
egress remain unaffected, while the exporter remains ClusterIP-only.

## Post-merge rollout

1. Select and independently confirm the staging kubeconfig and cluster identity.
2. Review `just observability-blackbox-render env=staging` without applying it.
3. The staging exporter release already exists, so run
   `just observability-blackbox-upgrade env=staging`. Install remains reserved
   for a genuinely absent release on a fresh staging cluster.
4. Run status, then verify. Preserve this output as separate live evidence.
5. Stop and investigate rather than attempting production if any guard fails.

Repository tests perform no live mutation. No live deployment was performed as
part of this repository change; repository state is not evidence of a live
rollout.

## Rollback

Inspect Helm history, roll back the exporter, then reapply the policy and Probe
renders from the matching Git revision and verify:

```bash
helm -n monitoring history prometheus-blackbox-exporter
helm -n monitoring rollback prometheus-blackbox-exporter <prior-revision> --wait --timeout 20m
kubectl apply -k clusters/staging/observability/network-policies
kubectl apply -k clusters/staging/observability/probes
just observability-blackbox-verify env=staging
```

Restore the corresponding version and complete values file before a subsequent
forward upgrade. The one-time legacy cleanup is not undone by Helm rollback;
restoring those former production Probe objects, if actually intended on the
staging cluster, requires an explicit application of an approved historical
manifest. Never restore them by applying the retained legacy mixed matrix.
Do not use `--reuse-values`.

## Troubleshooting

- **Missing CRDs/base stack:** install or repair the canonical stack through
  its own lifecycle; do not apply Flux CRDs or bypass preflight checks.
- **Failed Probe:** use bounded app/route labels to distinguish the route, then
  inspect exporter and application logs without copying headers or target
  payloads into tickets.
- **TLS, DNS, or HTTP failures:** validate certificate trust/expiry, in-cluster
  DNS resolution, and the documented status/body contract respectively. TLS
  certificate validation must remain enabled.
- **Absent Prometheus series:** check the ServiceMonitor label is exactly
  `release: kube-prometheus-stack`, confirm Probe discovery, and allow the
  bounded convergence window for initial scrapes.

## Legacy Flux ownership boundary

`platform/observability/prometheus-blackbox-exporter.yaml` and
`monitoring/probes/public-apps.yaml` are retained as `LEGACY/FUTURE ONLY`
references and are absent from every active Kustomize graph. They must not be
applied. Production Probe ownership is outside this staging-only lifecycle. The staging
helper neither manages production nor supplies a replacement production
lifecycle. Any future Flux adoption
of the exporter, policy, or staging Probes must first retire the manual lifecycle and
must never manage the same Helm release or Probe object names simultaneously.
