# Staging and production blackbox monitoring

Public-route monitoring has a guarded, environment-aware, **non-Flux** lifecycle. The
exporter, Prometheus, and their administrative interfaces remain LAN/internal
only. The exporter is a `ClusterIP` service; this work adds no Ingress,
NodePort, public DNS, router rule, credential, or persistence. The lifecycle
owns one NetworkPolicy per environment that permits only the canonical
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
- Complete environment values:
  `clusters/{staging,prod}/observability/prometheus-blackbox-exporter.values.yaml`.
- Lifecycle-owned Probes and deterministic Kustomize entrypoints:
  `clusters/{staging,prod}/observability/probes/`.
- Lifecycle-owned NetworkPolicies and deterministic Kustomize entrypoints:
  `clusters/{staging,prod}/observability/network-policies/`; the canonical manifest is
  `prometheus-to-blackbox-exporter.yaml`.
- Helper: `scripts/observability_blackbox.sh`, exposed by
  `just observability-blackbox-*`.
- Alert delivery for the probe signals defined here (`PublicEndpointDown`, `PublicProbeMissing`,
  `TLSExpiringSoon`): see the canonical [`docs/observability-alerting.md`](observability-alerting.md).

Repository configuration is not evidence that these resources are deployed.
Live evidence comes only from the separate post-merge rollout and validation.

## Probe quota safety contract

The application owners and observability reviewers jointly own the declarative
contracts in `platform/observability/probe-quotas/*.json`. Each application has
one reviewable file. The files describe the staging and production Probe name,
route class, exact application-owned path, method, interval, enabled state,
shared bucket, hourly and daily limits, exact exemptions, Prometheus scrape
fanout, per-execution request multiplier, safety margin, and whether the route
has been explicitly reviewed as unlimited. Application-specific quota facts
belong in those files; `scripts/validate_probe_quotas.py` contains no
application-name branches. The unlimited declarations currently record that no
application quota applies to those public or operational reads. They are not an
inference from successful HTTP responses and must be changed if an application
adds a quota.

For a window of `W` seconds and interval `I` seconds, each enabled,
non-exempt Probe contributes:

```text
scheduled requests = ceil(W / I) * fanout * requestMultiplier
usable budget      = floor(reviewed limit * (1 - safetyMargin))
```

The validator uses `W=3,600` for hourly limits and `W=86,400` for daily
limits. It sums scheduled requests from every enabled, non-exempt Probe with
the same application and bucket before comparing either window. A volume that
**reaches or exceeds** the usable budget fails; equality is deliberately
unsafe. Disabled declarations contribute zero. An unlimited route passes only
when `unlimited` is explicitly `true`, both limits are explicitly `null`, and
the declaration has no contradictory exemptions. Fanout must equal the
rendered Prometheus replica count, and `requestMultiplier` accounts for any
probe execution that generates more than one application request.

Exemptions are exact `(path, method)` pairs. Therefore a `GET /api/v1/meta`
exemption says nothing about `HEAD`, `POST`, `/api/v1/meta/`, a prefix, a
suffix, or a near-match path. Both `GET` and `HEAD` must be listed when both are
exempt. Missing fields, unknown methods, malformed durations, invalid limits
or margins, duplicate declarations, contradictory shared-bucket policy, and
unknown exporter modules all fail closed. Diagnostics contain only
repository-owned application, environment, Probe, route/bucket classes, and
calculated budgets; target hosts, headers, credentials, and source identities
are never printed.

The entrypoint reads only the active lifecycle Kustomize graphs at
`clusters/{staging,prod}/observability/probes/kustomization.yaml`, follows their
local `resources`, and rejects unsupported transformations. It derives the
actual path from each rendered static target, the actual method from that
environment's blackbox module, and the fanout from the base plus environment
Prometheus values. Every active Probe needs one enabled contract, every enabled
contract needs one active Probe, and staging and production are checked
independently. The legacy `monitoring/probes/public-apps.yaml` is never read.

Run the standalone, read-only check for both environments with:

```bash
just observability-probe-quotas
# or
python3 scripts/validate_probe_quotas.py --env staging --env prod
```

The same check runs explicitly in `.github/workflows/tests.yml` and inside the
blackbox lifecycle render before any install or upgrade can apply a Probe. A
failure means the manifest and reviewed quota policy are inconsistent or the
worst-case schedule is unsafe; do not use current endpoint health or historical
traffic to waive it.

To add or change a Probe, update its active environment manifest, blackbox
module when necessary, and application contract together. Choose an existing
bucket only when requests truly share that quota counter, record the actual
replica fanout and request multiplier, and obtain application-owner review for
limits, margins, exemptions, or unlimited status. A new application can be
tested without changing shared code by placing its schema-version-1 JSON file
in a temporary directory and passing `--config-dir DIRECTORY`.

The token.place incident demonstrates the boundary: one request every 60
seconds schedules 1,440 requests per day, which reaches a 1,000/day ordinary
quota even before reserving the 20% safety margin. The production-equivalent
root and metadata contracts pass only because their exact paths explicitly
list corrected `GET` and `HEAD` exemptions. Removing either route's exemption,
or probing it with an unlisted method, makes validation fail.

## Prerequisites and commands

The canonical `kube-prometheus-stack` Helm release, its `Probe` and
`ServiceMonitor` CRDs, and its Prometheus service must already exist in
`monitoring`. For staging live commands, select a kubeconfig whose current context
is exactly `sugar-staging`; the helper also runs the repository cluster-identity
assertion. Production live commands require an explicitly set `KUBECONFIG`, the
exact `sugar-prod` context, and a successful production identity assertion before
any release query or mutation. Offline rendering never reads kubeconfig or contacts Kubernetes.
Install `helm`, `kubectl`, `python3`, `ruby` (with Psych), and `just`, and ensure chart-repository
access is available.

```bash
just observability-blackbox-render env=staging
just observability-blackbox-install env=staging
just observability-blackbox-upgrade env=staging
just observability-blackbox-status env=staging
just observability-blackbox-verify env=staging

# Repository-ready production lifecycle (only during an approved rollout):
just observability-blackbox-render env=prod
KUBECONFIG=/path/to/explicit-prod-kubeconfig just observability-blackbox-install env=prod
KUBECONFIG=/path/to/explicit-prod-kubeconfig just observability-blackbox-upgrade env=prod
KUBECONFIG=/path/to/explicit-prod-kubeconfig just observability-blackbox-status env=prod
KUBECONFIG=/path/to/explicit-prod-kubeconfig just observability-blackbox-verify env=prod
```

Render, status, and verify are read-only. Status displays the exact owned
NetworkPolicy. Install is only for an absent exporter release; upgrade requires
it to exist. Both render the pinned chart, policy, and Probes first, pass the
complete committed values on every Helm operation, and wait up to the
Pi-appropriate timeout. Only after Helm succeeds, they apply the policy and then
the rendered Probes. After the desired Probes are applied, the helper prunes
same-environment objects selected by the exact `release: kube-prometheus-stack`
and selected `environment` labels, deleting only names absent from the rendered
desired set. In staging only, it also deletes the eleven exact cross-environment
legacy names listed in the helper's `LEGACY_PROBES`; production performs no
cross-environment legacy cleanup. Both cleanup paths run after the context and
identity guards and the desired Probe apply, and both use `--ignore-not-found`.
An empty stale set is a no-op. Probes outside either the exact selector or, in
staging, the exact legacy-name set remain untouched. Rendering, YAML parsing,
listing, and comparison all fail closed before deletion. A Helm failure makes
no policy or Probe mutation; a policy apply failure prevents Probe mutation.
Neither environment uses `--reuse-values`.
Missing and unsupported environments fail before cluster access; `env=int` is
a deprecated staging alias and `production` normalizes to `prod`.

## Exact staging matrix

| App | Base URL | Routes |
| --- | --- | --- |
| DSPACE (`dspace`) | `https://staging.democratized.space` | `/` (`root`), `/config.json` (`config`), `/healthz` (`healthz`), `/livez` (`livez`) |
| token.place (`tokenplace`) | `https://staging.token.place` | `/` (`root`), `/healthz` (`healthz`), `/livez` (`livez`), `/api/v1/meta` (`metadata`) |
| danielsmith.io (`danielsmith`) | `https://staging.danielsmith.io` | `/` (`root`), `/healthz` (`healthz`), `/livez` (`livez`) |
| GitShelves (`gitshelves`) | `https://staging.gitshelves.com` | `/` (`root`), `/healthz` (`healthz`), `/livez` (`livez`), `/models/baseplate_2x6.stl` (`baseplate`), `/models/contrib_cube.stl` (`module`) |
| jobbot3000 | `https://staging.jobbot3000.tech` | `/` (`root`), `/healthz` (`healthz`), `/livez` (`livez`), `/tracker` (`tracker`), `/manifest.webmanifest` (`manifest`) |


GitShelves Probes must be applied and verified only after its staging workload and external Cloudflare Tunnel route exist. GitShelves exposes no `/metrics`, so it has no ServiceMonitor.

All five GitShelves Probes have been separately verified and activated. The
guarded WAN drill now validates and contacts all 21 approved-live endpoints.
GitShelves activation is all-or-none; partial activation remains invalid and is
rejected by the lifecycle guard.

These are exactly 21 Probes. Labels are bounded to `release`, `app`,
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


## Exact production matrix and rollout status

Production coverage follows applications that have both a production deployment
and DNS-routable, verified production endpoints. It mirrors the corresponding
staging modules, intervals, criticalities, TLS checks, body limits, and content
contracts for these 11 routes:

| App | Base URL | Routes |
| --- | --- | --- |
| DSPACE (`dspace`) | `https://democratized.space` | `/` (`root`), `/config.json` (`config`), `/healthz` (`healthz`), `/livez` (`livez`) |
| token.place (`tokenplace`) | `https://token.place` | `/` (`root`), `/healthz` (`healthz`), `/livez` (`livez`), `/api/v1/meta` (`metadata`) |
| danielsmith.io (`danielsmith`) | `https://danielsmith.io` | `/` (`root`), `/healthz` (`healthz`), `/livez` (`livez`) |

Names use
`blackbox-<app>-prod-<route>` and labels use `environment: prod`.

GitShelves and jobbot3000 remain fully covered in staging but have no active
production Probes. Add their production Probes only in a reviewed change after
each application's production promotion, public DNS, Cloudflare Tunnel route,
and all intended endpoint checks succeed. Dormant Helm examples and promotion
documentation do not satisfy this activation gate.

This production lifecycle is **repository-ready, not live deployment
evidence**. The exporter, Probes, metric series, dashboard population, and
alerts must not be described as deployed until a separate approved operator
rollout and `env=prod` verification produces retained evidence.

## Post-merge rollout

1. Select and independently confirm the intended kubeconfig and cluster identity.
2. Review the selected environment's offline render without applying it.
3. The staging exporter release already exists, so run
   `just observability-blackbox-upgrade env=staging`. Install remains reserved
   for a genuinely absent release on a fresh staging cluster.
4. Run status, then verify. Preserve this output as separate live evidence.
5. During a separately approved production rollout, use install only if status
   confirms the exporter is absent; otherwise use upgrade. Stop if any guard fails.

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

# Production uses the same sequence after enforcing its explicit guards:
export KUBECONFIG=/path/to/explicit-prod-kubeconfig
test -n "$KUBECONFIG"
test "$(kubectl config current-context)" = sugar-prod
python3 scripts/cluster_identity.py assert --kubeconfig "$KUBECONFIG" --env prod
helm -n monitoring history prometheus-blackbox-exporter
helm -n monitoring rollback prometheus-blackbox-exporter <prior-revision> --wait --timeout 20m
kubectl apply -k clusters/prod/observability/network-policies
kubectl apply -k clusters/prod/observability/probes
just observability-blackbox-verify env=prod
```

Restore the corresponding version and complete values file before a subsequent
forward upgrade. Same-environment Probe reconciliation follows the checked-out
desired manifest; staging additionally deletes the eleven exact cross-environment
names in `LEGACY_PROBES`, rather than deriving those deletions from that manifest.
Production performs no such cross-environment cleanup. Do not restore removed
production Probe objects unless their production activation gate has been
satisfied in a reviewed change. Never restore them by applying the retained
legacy mixed matrix. Do not use `--reuse-values`.

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
applied. Production Probe ownership is provided by the guarded manual lifecycle but is
not claimed live. Any future Flux adoption
of the exporter, policy, or staging Probes must first retire the manual lifecycle and
must never manage the same Helm release or Probe object names simultaneously.
