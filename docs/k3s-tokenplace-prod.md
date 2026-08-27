# k3s token.place runbook (prod)

Use this environment runbook for production token.place operations after staging sign-off. The full uniform GHCR-first flow lives in [docs/apps/tokenplace.md](apps/tokenplace.md); this page keeps the production commands copy-pasteable.

## Scope and ownership

- App repo: publishes `ghcr.io/futuroptimist/tokenplace-relay` and `oci://ghcr.io/futuroptimist/charts/tokenplace`.
- Sugarkube: selects `env=prod`, deploys the pinned chart with the approved immutable image tag, and verifies the release.
- Cloudflare: routes `token.place` to Traefik outside Helm.


### Required staging sign-off before promotion

Production promotion is blocked until staging proves the actual relay-compute path, not just web/TLS health. Confirm these staging artifacts before running the prod command:

- [ ] `app-status`, `app-verify`, `/healthz`, `/livez`, and `/relay/diagnostics` passed for staging.
- [ ] A real external desktop or compute node registered to `staging.token.place` and appeared in staging `/healthz` and `/relay/diagnostics`.
- [ ] A real E2EE request/response succeeded through that staging-registered compute node.
- [ ] The `token.place` Cloudflare route points at Traefik before prod cutover.

## Promote production

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

Preferred generic command:

```bash
just app-promote-prod app=tokenplace tag="$APP_TAG"
```

Compatibility shim while migration is in progress:

```bash
just tokenplace-oci-promote-prod tag="$APP_TAG"
```

## Verify production

```bash
just app-status app=tokenplace env=prod
```

```bash
just app-verify app=tokenplace env=prod
```

```bash
curl -fsS https://token.place/relay/diagnostics | jq .
```

### Required production relay proof

Do not mark production healthy on generic checks alone. Capture separate production relay evidence after promotion:

- [ ] A real external desktop or compute node is configured for `token.place`, registers to production, and does not silently fall back to staging.
- [ ] The production-registered compute node appears in prod `/healthz` and `/relay/diagnostics`.
- [ ] A real E2EE request/response succeeds through the production-registered compute node.
- [ ] Post-test `/healthz`, `/relay/diagnostics`, and relay logs are captured after the E2EE test.

```bash
TOKENPLACE_HOST=token.place
kubectl --context sugar-prod -n tokenplace get deploy tokenplace -o yaml > /tmp/tokenplace-prod-deployment.yaml
# First run real prod compute-node registration and the prod E2EE
# request/response. Then capture post-test evidence:
curl -fsS "https://${TOKENPLACE_HOST}/healthz" | tee /tmp/tokenplace-prod-healthz.json
curl -fsS "https://${TOKENPLACE_HOST}/relay/diagnostics" | tee /tmp/tokenplace-prod-diagnostics.json
kubectl --context sugar-prod -n tokenplace logs deploy/tokenplace --since=30m --tail=500 \
  | tee /tmp/tokenplace-prod-relay-after-compute.log
```

## Rollback production

```bash
APP_TAG=main-REPLACE_PREVIOUS_SHORTSHA
```

```bash
just app-redeploy app=tokenplace env=prod tag="$APP_TAG"
```

## Production compute-capacity alerts

The chat UI's **Live compute nodes** value comes from
`total_api_v1_registered_compute_nodes` in `/relay/diagnostics`; the relay evicts expired
registrations before returning it. Prometheus' `tokenplace_compute_nodes_healthy` uses the same
lease-expiry availability semantics and is the paging signal. `TokenplaceNoHealthyComputeNodes`
therefore pages after an explicit zero remains for five minutes, regardless of queue depth or
current demand. It additionally requires a successful production scrape and
`tokenplace_instrumentation_up == 1`. Missing, stale, undiscovered, or failed telemetry cannot
become a zero; `TokenplaceMetricsTargetDown` reports that distinct monitoring failure after ten
minutes while the relay workload is expected to run.

### Deployment and verification order

Do not place a token in Git, a manifest, shell history, or command arguments. In an authorized
production session, use the existing hidden-input recipe to create
`tokenplace/tokenplace-prod-metrics-token` with key `token`, and check only key presence:

```bash
just observability-app-metrics-secret-install app=tokenplace env=prod
just observability-app-metrics-secret-check app=tokenplace env=prod
```

Then deploy the pinned token.place production revision (whose production values enable authenticated
metrics and its ServiceMonitor), verify the scrape contract, and finally deploy and verify the
observability revision containing the rules and exact PagerDuty route:

```bash
just app-redeploy app=tokenplace env=prod tag="$APP_TAG"
just observability-app-metrics-verify app=tokenplace env=prod
just observability-render env=prod
# Separately authorized change window only:
just observability-upgrade env=prod
just observability-verify env=prod
```

### Triage and Mac Mini recovery

Acknowledge the PagerDuty incident first and confirm whether its alert name is the capacity alert or
the telemetry alert. Query Prometheus with these exact production selectors (through the protected
Prometheus UI/API); do not expose `/metrics` credentials:

```promql
tokenplace_compute_nodes_healthy{app="tokenplace",environment="prod",cluster="sugarkube-prod",namespace="tokenplace",release="tokenplace"}
tokenplace_compute_nodes_registered{app="tokenplace",environment="prod",cluster="sugarkube-prod",namespace="tokenplace",release="tokenplace"}
max(tokenplace_compute_node_lease_age_seconds{app="tokenplace",environment="prod",cluster="sugarkube-prod",namespace="tokenplace",release="tokenplace"})
tokenplace_instrumentation_up{app="tokenplace",environment="prod",cluster="sugarkube-prod",namespace="tokenplace",release="tokenplace"}
up{app="tokenplace",environment="prod",cluster="sugarkube-prod",namespace="tokenplace",release="tokenplace"}
tokenplace_relay_queue_depth{app="tokenplace",environment="prod",cluster="sugarkube-prod",namespace="tokenplace",release="tokenplace"}
sum by (reason) (rate(tokenplace_compute_node_evictions_total{app="tokenplace",environment="prod",cluster="sugarkube-prod",namespace="tokenplace",release="tokenplace"}[15m]))
```

For the Mac Mini M4 Pro compute host, use the host's approved access procedure; this repository does
not store its hostname, login, keys, or connector credentials. Confirm power and network, inspect the
operator-managed compute process or launch service, restart only that process if necessary, and
confirm it registers to `https://token.place` (not staging). Verify diagnostics and the healthy and
registered queries return above zero, lease age resumes updating, the capacity alert resolves, and
PagerDuty records the resolved notification before resolving the acknowledged incident. If telemetry
is down, restore the ServiceMonitor/authentication path first rather than treating it as capacity loss.

### Rollback and controlled drill

To back out only this paging behavior, remove the exact `pagerduty-tokenplace` route/receiver and the
`tokenplace-production` rule overlay in a reviewed observability revision; leave the
`healthchecks-watchdog` route and Secret untouched. Alternatively, roll back only
`kube-prometheus-stack` to the immediately preceding known-good Helm revision. Disabling the alert
does not require changing retention, storage, the relay, or compute heartbeat behavior.

After merge and deployment, schedule (do not improvise) a controlled drill: acknowledge the change,
stop or unregister the production compute process, wait at least five continuous minutes for
`TokenplaceNoHealthyComputeNodes` and its PagerDuty incident, acknowledge the incident, restore and
re-register the Mac Mini node, and confirm both the Prometheus alert and PagerDuty incident resolve.
Abort if scrape or instrumentation health fails; that is a telemetry drill, not proof of zero-capacity
paging. This repository change documents the drill but does not perform it or send test events.

## Cloudflare route

Cloudflare Tunnel routing is external to Helm.

```bash
just cf-tunnel-route host=token.place
```

## Troubleshooting

```bash
just app-config app=tokenplace env=prod
```

```bash
just tokenplace-debug-logs-env env=prod
```
