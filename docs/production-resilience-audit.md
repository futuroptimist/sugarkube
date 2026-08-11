# Production resilience parity audit

This audit is the read-only prerequisite to any production DNS, ingress, or Cloudflare Tunnel
high-availability proposal. It inventories the live cluster and compares observations with the
contract proven by the staging WAN drill. It does **not** deploy, patch, restart, delete, reconcile,
or render changes, and it does not invoke `cf-tunnel-install`. The current non-staging behavior of
that recipe is materially different from the staging lifecycle and is not an approved production
promotion mechanism. Dormant `platform/cloudflared` and `clusters/*/patches/cloudflared-values.yaml`
resources are not treated as live ownership.

Run from `sugarkube0` or another authorized operator host. Explicitly select the production
kubeconfig first; its current context must be exactly `sugar-prod`, the repository identity check
must report `prod`, and the observed nodes must be exactly `sugarkube0`, `sugarkube1`, and
`sugarkube2`.

```bash
export KUBECONFIG="$HOME/.kube/config-sugarkube-prod"
test "$(kubectl config current-context)" = sugar-prod
just prod-resilience-audit env=prod --evidence-dir="$PWD/prod-audit-evidence"
```

The default exit status is successful when collection completes, even when the report contains
expected parity gaps. Use `--require-parity` in a gate that should fail when any stable gap code is
present:

```bash
just prod-resilience-audit env=prod --evidence-dir="$PWD/prod-audit-gate" --require-parity
```

The evidence directory contains deterministic, sanitized `audit.json`, `summary.md`,
`endpoints.tsv`, and `SHA256SUMS`. Kubernetes Secret resources and values, Helm values, pod logs,
raw Prometheus label sets, and tunnel connector identifiers are never queried or retained. Public
requests are bounded and run independently; evidence records only URLs, status codes, bounded
timings, and sanitized error classes. The committed target list is narrowly scoped in
`config/prod-resilience-audit-targets.json`, based on each application's production runbook.

Review all evidence before designing a separate, explicitly reviewed production lifecycle and
rollout PR. This audit does not select a replica count. No production WAN-loss or node-loss drill is
authorized. The staging work in issue #2407 remains closed; issue #2408 remains open, separate
application-replica work and is not changed by this audit.
