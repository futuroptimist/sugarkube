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

## Production compute capacity alerts

Production pages on two deliberately separate failures:

- `TokenplaceNoHealthyComputeNodes` means the relay explicitly reported zero
  lease-healthy compute nodes for five continuous minutes while the Prometheus
  scrape and `tokenplace_instrumentation_up` were both healthy. It is actionable
  even when the queue is empty.
- `TokenplaceMetricsTargetDown` means the authenticated production metrics target
  was down or undiscovered while the relay workload was expected to run for ten
  minutes. Missing, stale, or failed telemetry never becomes a zero-node value.

The chat UI's **Live compute nodes** value comes from
`total_api_v1_registered_compute_nodes` in `/relay/diagnostics`; the relay evicts
stale registrations before returning it. The alert uses
`tokenplace_compute_nodes_healthy`, which applies the same lease-expiry
availability semantics and is therefore the paging signal rather than raw demand
or queue depth.

### Provision and deploy authenticated metrics

Production temporarily uses the Llama 3.1 maintenance relay line. Its verifier
contract intentionally requires only `tokenplace_compute_nodes_registered`,
`tokenplace_compute_nodes_healthy`, `tokenplace_instrumentation_up`, and
`tokenplace_build_info`. The approved immutable candidate is
`ghcr.io/futuroptimist/tokenplace-relay:sha-f5c6d6b`, built from source commit
`f5c6d6b0306112718d74a8340f39f35551b657e6`. Those four families are sufficient
for zero-healthy-compute-node and telemetry-loss paging. The verifier selects
this compatibility contract only when the live relay reports the approved
`sha-f5c6d6b` image tag; every other production image must satisfy the full
13-family contract. Staging remains on the modern Qwen relay and retains that
full contract.

Create `tokenplace/tokenplace-prod-metrics-token` with key `token` before deploying
production values. No Secret manifest belongs in Git. From a private interactive
terminal, use the existing hidden-input recipe; do not pass the value as an
argument, environment variable, or redirected file:

```bash
just observability-app-metrics-secret-install app=tokenplace env=prod
```

Then follow this order:

```bash
just observability-app-metrics-secret-check app=tokenplace env=prod
just app-redeploy app=tokenplace env=prod tag="$APP_TAG"
just observability-app-metrics-verify app=tokenplace env=prod
just observability-render env=prod
```

The verifier checks the Secret's existence and nonempty key without reading or
printing its value, expects unauthenticated `https://token.place/metrics` to
return 401, and validates target identity, required families, and bounded labels.
Only after those checks pass should an operator upgrade the production
observability release through its normal reviewed lifecycle.

### Diagnosis and Mac Mini recovery

Use Prometheus (or Grafana Explore) for these credential-free queries:

```promql
tokenplace_compute_nodes_healthy{environment="prod",cluster="sugarkube-prod"}
tokenplace_compute_nodes_registered{environment="prod",cluster="sugarkube-prod"}
tokenplace_compute_node_lease_age_seconds{environment="prod",cluster="sugarkube-prod"}
tokenplace_instrumentation_up{environment="prod",cluster="sugarkube-prod"}
up{app="tokenplace",environment="prod",cluster="sugarkube-prod",namespace="tokenplace",release="tokenplace"}
tokenplace_relay_queue_depth{environment="prod",cluster="sugarkube-prod"}
tokenplace_compute_node_evictions_total{environment="prod",cluster="sugarkube-prod"}
```

For the production Mac Mini M4 Pro, use the host's existing secure access method;
no host credential is stored here. Confirm power and networking, start or restart
the installed compute-node service, verify it is configured for the production
`token.place` relay (not staging), and use its local service manager/logs to
confirm registration and lease renewal. Then confirm diagnostics and the healthy,
registered, lease-age, and eviction queries recover. Do not restart the relay
merely to manufacture a registration.

Acknowledge the PagerDuty incident while investigating. After restoration,
confirm the Prometheus alert becomes inactive and the same incident resolves via
`send_resolved: true`; do not create a second test event. For a metrics-target
page, repair discovery/authentication first and do not interpret the incident as
proof that compute is absent.

### Controlled post-merge drill

Do this only in an approved maintenance window after the Secret, metrics deploy,
rules, and route have been verified. Do **not** perform it as part of a repository
change:

1. Stop or explicitly unregister the production compute service on the Mac Mini.
2. Confirm diagnostics and the healthy-node metric explicitly reach zero.
3. Wait at least five continuous minutes, then confirm
   `TokenplaceNoHealthyComputeNodes` fires and its PagerDuty incident arrives.
4. Acknowledge the incident, restore/re-register the compute service, and confirm
   lease renewal and a successful real request.
5. Confirm the Prometheus alert clears and PagerDuty resolves the incident.

### Focused rollback

To disable only this paging path, remove the exact `pagerduty-tokenplace` route
and receiver and the `tokenplace-production` rules overlay in a reviewed
observability revision; leave `healthchecks-watchdog`, its Secret, and the
watchdog rule untouched. Alternatively, redeploy the previous known-good
Sugarkube observability revision using the standard Helm lifecycle. Disabling the
alert must not disable authenticated application metrics, existing DSPACE or
Cloudflare routes, the synthetic test route, or the watchdog.

### TokenplaceMetricsTargetDown

Check the production ServiceMonitor selector, `tokenplace-prod-metrics-token`
name/key wiring, ready relay pod, network reachability, and Prometheus Targets
page. Restore the target and wait for the ten-minute alert to resolve; investigate
compute capacity separately.
