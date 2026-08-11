# Production resilience parity audit

The production resilience audit is a **read-only inventory**, not a deployment
lifecycle. It compares the observed production DNS, ingress, and Cloudflare
Tunnel state with the contracts proven by the staging WAN exercise. Run it from
`sugarkube0`, or another authorized operator host, only after explicitly
selecting a kubeconfig whose current context is exactly `sugar-prod`:

```bash
KUBECONFIG="$HOME/.kube/config" just prod-resilience-audit env=prod \
  --evidence-dir="$HOME/prod-resilience-evidence"
```

The command also requires the repository cluster identity to report `prod` and
the exact node set `sugarkube0`, `sugarkube1`, and `sugarkube2`. Identity or
collection failures return exit status 2. A completed collection returns zero
even when it reports `PARITY_GAPS`; add `--require-parity` when automation must
return nonzero for gaps.

The evidence directory contains deterministic JSON and Markdown summaries,
bounded endpoint timings, and `SHA256SUMS`. It contains resource metadata,
desired non-secret workload configuration, Secret **references**, and aggregate
Prometheus counts. It never requests Secret objects or pod logs, and it does not
retain connector IDs, raw metric labels, credentials, or response bodies.

## Safety boundary

The implementation has a small executable allowlist and rejects mutating
Kubectl and Helm verbs. It never invokes Flux, SSH, node administration, a WAN
dependency-loss drill, or the existing `cf-tunnel-install` recipe. In
particular, that non-staging install behavior is materially different and is
not an approved production promotion mechanism.

This change performs no production rollout. Review `audit.json`, `summary.md`,
`endpoints.tsv`, and their checksums before designing a separate, independently
reviewed production lifecycle and rollout pull request. No production WAN-loss
or node-loss drill is authorized. Issue #2407 remains closed; application
replica issue #2408 remains open and separate.

The narrow target inventory in
`config/prod-resilience-audit-targets.json` is repository-owned because the
mixed legacy/future monitoring graph is not authoritative production state.
It covers the approved root, health, live, configuration, and metadata surfaces
for democratized.space, token.place, and danielsmith.io. Each request runs in
its own bounded worker so one timeout does not serialize or delay the others.
