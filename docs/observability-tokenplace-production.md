# token.place production capacity alerting runbook

This runbook covers the production-only `TokenplaceNoHealthyComputeNodes` and
`TokenplaceMetricsTargetDown` alerts. The former means the relay explicitly reported zero
lease-healthy compute nodes for five continuous minutes. It is actionable even when the request
queue is empty. The latter means the expected relay workload has had no healthy authenticated
Prometheus target for ten minutes. Missing, stale, undiscovered, or failed telemetry is never
interpreted as zero capacity.

The chat UI's **Live compute nodes** value comes from
`/relay/diagnostics` field `total_api_v1_registered_compute_nodes` after stale registrations are
evicted. `tokenplace_compute_nodes_healthy` applies the relay's same lease-expiry availability
semantics and is the paging signal; `tokenplace_compute_nodes_registered` remains a useful
comparison signal.

## Provision and deploy in order

The required Secret is `tokenplace/tokenplace-prod-metrics-token`, key `token`. Do not add a Secret
manifest, place a value on a command line, or retrieve, print, hash, or compare the value. On a
trusted operator terminal, install it with the existing no-echo, hidden-input recipe:

```bash
just observability-app-metrics-secret-install app=tokenplace env=prod
just observability-app-metrics-secret-check app=tokenplace env=prod
```

Then deploy the token.place production chart revision, which enables authenticated metrics and its
30-second `ServiceMonitor`, before upgrading observability so the alert cannot mistake an
undiscovered target for capacity:

```bash
just app-promote-prod app=tokenplace
just app-verify app=tokenplace env=prod
just observability-upgrade env=prod
just observability-app-metrics-verify app=tokenplace env=prod
just observability-verify env=prod
```

The generic verifier checks the Secret reference without reading its value, confirms target
discovery and scrape health, requires the bounded metric families and labels, and confirms that an
unauthenticated request to `https://token.place/metrics` is rejected. Review rendered output before
a live upgrade with `just observability-render env=prod`; repository validation must not access a
cluster.

## TokenplaceNoHealthyComputeNodes

A page identifies explicit zero usable production capacity while `up == 1` and
`tokenplace_instrumentation_up == 1`. It is not gated on queue depth or present demand. In
Prometheus, inspect:

```promql
tokenplace_compute_nodes_healthy{environment="prod",cluster="sugarkube-prod",namespace="tokenplace",release="tokenplace"}
tokenplace_compute_nodes_registered{environment="prod",cluster="sugarkube-prod",namespace="tokenplace",release="tokenplace"}
tokenplace_compute_node_lease_age_seconds{environment="prod",cluster="sugarkube-prod",namespace="tokenplace",release="tokenplace"}
tokenplace_instrumentation_up{environment="prod",cluster="sugarkube-prod",namespace="tokenplace",release="tokenplace"}
up{app="tokenplace",environment="prod",cluster="sugarkube-prod",namespace="tokenplace",release="tokenplace"}
tokenplace_relay_queue_depth{environment="prod",cluster="sugarkube-prod",namespace="tokenplace",release="tokenplace"}
rate(tokenplace_compute_node_evictions_total{environment="prod",cluster="sugarkube-prod",namespace="tokenplace",release="tokenplace"}[15m])
```

For the production Mac Mini M4 Pro compute node, use its locally documented operator access; this
repository intentionally contains no host credentials. Confirm power and network connectivity,
inspect the locally installed compute service with the service manager used during installation,
and restart that service if stopped. Confirm its configuration selects `https://token.place` rather
than staging. Watch its local logs for successful registration/lease renewal without copying
sensitive configuration into an incident. Finally confirm the diagnostics live-node value and the
healthy metric return above zero, then complete one real end-to-end encrypted request using the
release's documented operator workflow. Do not invent synthetic registration calls.

In PagerDuty, acknowledge the incident, record whether the node lost power, connectivity, service
health, or registration, and verify that Alertmanager's `send_resolved` event resolves the same
incident after the metric recovers. If it does not resolve, compare the alert fingerprint labels and
Alertmanager status before creating a second incident.

## TokenplaceMetricsTargetDown

Treat this as a monitoring blind spot, not proof of zero compute capacity. Check the production
workload readiness, `ServiceMonitor` discovery, the Secret name/key contract, network access, and
Prometheus target error without decoding the bearer credential. A healthy `up` series prevents this
alert; restoring a failed or missing target resolves it. Acknowledge and verify resolution in
PagerDuty independently from any capacity incident.

## Rollback

To disable only this paging path while retaining the production watchdog, remove or revert the
`pagerduty-tokenplace` exact route and the `tokenplace-production-capacity` rule group, render and
review, then perform the normal observability upgrade. Alternatively, roll back to the immediately
preceding reviewed observability Helm revision. Do **not** remove or alter
`healthchecks-watchdog`, its Secret, or `SugarkubeObservabilityWatchdog`; verify Healthchecks **Last
Ping** still advances after rollback. Disabling token.place chart metrics is a separate application
rollback and should happen only after the alert rules no longer depend on them.

## Controlled post-merge drill

Do not run this drill during repository validation. In an approved production window, confirm
scrape and instrumentation health first; stop or explicitly unregister the production compute
service on the Mac Mini; and leave the relay running. Confirm the live/healthy value becomes zero,
wait at least five continuous minutes for `TokenplaceNoHealthyComputeNodes`, and confirm the exact
production PagerDuty incident arrives. Acknowledge it. Restore the compute service, confirm it
registers and renews its lease, verify the healthy metric rises above zero, and confirm the same
PagerDuty incident resolves. Record timestamps and sanitized alert labels only—never credentials or
host secrets.
