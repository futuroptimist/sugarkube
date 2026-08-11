# Production resilience parity audit

This audit inventories production against the DNS, ingress, and Cloudflare Tunnel HA contracts
proven in staging. It is evidence collection, not a production rollout or an authorization to
change production.

Run it from `sugarkube0` or another authorized operator host after explicitly selecting the
`sugar-prod` kubeconfig:

```bash
KUBECONFIG="$HOME/.kube/config" just prod-resilience-audit env=prod \
  --evidence-dir="evidence/prod-resilience-$(date -u +%Y%m%dT%H%M%SZ)"
```

The command fails closed unless the context, repository cluster-identity result, and exact
three-node production inventory all agree. It uses only read operations and never reads Secret
values, pod logs, connector IDs, credentials, or user data. It probes only the narrowly scoped
targets in `config/production-resilience-audit-targets.json`; each request has independent bounded
timeouts. Evidence consists of deterministic sanitized JSON, a Markdown summary, endpoint TSV,
and SHA-256 manifest. A completed collection returns success even when it reports `PARITY_GAPS`;
add `--require-parity` when gaps should produce a nonzero exit status.

Review the captured evidence before designing a separate, separately reviewed production
lifecycle and rollout PR. Do **not** use the existing non-staging `cf-tunnel-install` behavior as
a promotion mechanism. Dormant `platform/cloudflared` and `clusters/*/patches/cloudflared-values.yaml`
resources are not treated as live ownership; the audit discovers the live Helm-owned Deployment.
No production WAN-loss or node-loss drill is authorized. Issue #2407 remains closed, while
#2408 remains open and separate application-replica work and is untouched by this workflow.
