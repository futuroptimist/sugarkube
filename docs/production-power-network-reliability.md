# Production power and network reliability design

Status: draft for human review; no hardware selection or live validation completed.

## Goal and boundaries

Keep the complete production service path available through loss of utility power,
fiber service, or both. The initial target is cellular connectivity plus battery
power for **three production Raspberry Pis** and every local dependency needed to
serve critical production traffic. Staging is excluded from the battery budget:
the requested scope reduces the Pi count from six to three, not the dependency
count to three.

This proposal authorizes no implementation, deployment, purchase, host access,
credential or security change, merge, or outage test. All measurement and validation
steps below are future work requiring the human gates at the end of this document.
No measurements, carrier suitability, or hardware compatibility are claimed here.

## Evidence and unknown topology

Hypothetical failure scenario: a status app could show a fiber gateway online
while a downstream router is unresponsive. Such status indicators would not be
independent tests of service continuity. An app status alone cannot distinguish
an upstream outage, stale status, local power loss, router failure, or a broken
link between devices; the root cause would remain unknown without further evidence.

Repository evidence describes intended configuration and historical observations,
not a current physical survey:

- [Network setup](network_setup.md) describes Ethernet switches and possible PoE
  or USB-C supplies, but does not establish installed wiring or power delivery.
- [Observability operations](observability-operations.md) records three production
  nodes and historical monitoring evidence. It does not prove current availability
  or the WAN traffic volume.
- [Cloudflare Tunnel](cloudflare_tunnel.md) describes an in-cluster connector and
  ingress path. Its placement, restart dependencies, and behavior on cellular must
  still be confirmed for the production installation.
- [Power system design](power_system_design.md) contains illustrative solar and
  battery calculations. Those example loads are not measurements for this design.

| Surface | Known or proposed role | Evidence still needed before design approval |
| --- | --- | --- |
| Upstream gateway (fiber in this scenario) | Primary internet handoff | Exact mode, power feed, handoff, actual link health, and whether it supplies any required LAN service |
| LAN router and DHCP/DNS services | Required routing, dynamic address assignment and name resolution | Which devices provide each function, supported WAN handoffs, lease renewal and DNS behavior on both paths |
| Cellular gateway | Proposed alternate internet path | Carrier, plan, reception, interface, routing mode, power draw and independent operation |
| WAN selection | Required way to select a working upstream path; device ownership unresolved | Manual versus automatic switching, supported interfaces and behavior when the WAN address changes |
| Necessary switches | Every switch on the production path must remain powered | Port and cable map, uplinks, power supplies, PoE loads and shared staging dependencies |
| Wireless access points | Conditional dependency if production connectivity or the approved recovery route uses WiFi | Whether needed at all, power and wired uplink dependencies, client isolation and local multicast behavior |
| Three production Pis | Outage compute target | Node roles, quorum, workload placement, local storage, power supplies and restart order |
| Tunnel and ingress | Repository documents Cloudflare Tunnel to cluster ingress | Production connector placement, DNS resolution, outbound connectivity, ingress, certificates, origins and external service dependencies |

The following is a **candidate functional path**, not a verified wiring diagram:

```text
Normal WAN:     upstream gateway (fiber) --+
                                         +-- WAN selection -- LAN router -- switches
Outage WAN:     cellular gateway ---------+                         |           |
                                                        DHCP/DNS services     |
                                                                    three production Pis
                                                                             |
                                                              tunnel / ingress / apps

Optional: required switches -- access point -- any required wireless clients

External clients <-> Cloudflare edge <-> outbound tunnel over the selected WAN
```

These are functional roles, not a requirement for separate boxes or a particular
brand. One device may combine routing, DHCP, DNS forwarding, Ethernet switching
and a wireless access point; verify each function rather than infer it from a
product label. DHCP/DNS services shown alongside the router may run elsewhere.

The local battery boundary includes the cellular gateway, required routing and
DHCP/DNS functions, all necessary switches and access points, the three Pis,
storage, cooling and their power conversion equipment. Include an access point
only if production or the approved recovery route needs it. External carrier
infrastructure, Cloudflare, public DNS and upstream application services remain
outside that boundary.

### Required capabilities and optional features

The design assumes a LAN routing function that can reach the selected upstream
gateway, working DHCP service for dynamic leases, DNS resolution through the
selected WAN, and local connectivity among the production nodes. Verify supported
WAN interfaces, gateway routing modes and outbound tunnel connectivity for the
actual equipment. A router may forward DNS rather than host a resolver itself;
the required property is working resolution on both paths without an unpowered
dependency. No specific router is assumed to provide all these functions.

Preserve intentional dynamic DHCP and mDNS discovery. Fixed IP addresses and DHCP
reservations are not prerequisites for this design. Verify lease acquisition and
renewal, including changed addresses after restart, plus local multicast delivery
and mDNS discovery on the production LAN. mDNS is local discovery, not a substitute
for upstream DNS resolution. Confirm that switch or access-point isolation does
not block required discovery; do not assume mDNS crosses routed network boundaries.
See [mDNS troubleshooting](mdns_troubleshooting.md) for the existing discovery model.

Automatic dual-WAN switching, bridge mode, VLANs, PoE and wireless mesh are optional
features, not universal router capabilities or requirements. A supported manual
handoff may be acceptable if it meets the human-approved recovery objective.
Document who performs it and how they retain access during an outage. Automatic
failover requires verified device support, health detection and recovery behavior;
this diagram does not imply such support. Likewise, do not assume a cellular gateway
can replace the LAN router or that a proposed UPS works with the installed supplies.

If production still needs a router for routing, DHCP, DNS or connectivity, its power
belongs in the initial battery budget. The same rule applies to required functions
in the upstream gateway, switches or access points. A later UPS for the primary
upstream gateway and any primary-only router is optional **only after the initial
cellular path is shown to operate with those devices absent**. A shared LAN router
remains an initial power dependency and a potential single point of failure.

## Failure modes and intended response

| Failure | Intended behavior and validation question |
| --- | --- |
| Fiber loss with utility power present | Use cellular; detect end-to-end failure even when an Ethernet link or app status remains up |
| Utility loss with fiber still available | Preserve the complete production path on battery; do not infer battery coverage from powered Pis alone |
| Simultaneous utility and fiber loss | Cellular plus the complete battery boundary serves the approved critical workload without staging |
| LAN router or upstream gateway failure | Independent outage path remains usable if provided; otherwise record the shared device as an unresolved single point of failure |
| Switch, uplink or power supply failure | Identify the affected production dependency; WAN redundancy alone does not repair a broken LAN |
| Cellular outage, poor reception or exhausted allowance | Declare degraded/unavailable service, alert through a verified reachable route, and follow the approved traffic policy |
| WAN address or route change | Observe tunnel reconnection, existing session interruption, DNS behavior and application recovery |
| Pi, storage or cluster dependency failure | Confirm critical workloads and control-plane quorum can recover with only the three production nodes |
| Battery depletion or repeated brownouts | Follow the approved shutdown reserve and restart order; prevent uncontrolled restart cycling |
| Cloudflare, DNS or external application outage | Distinguish local path health from external dependency failure; do not claim WAN switching solves it |

## Measurement plan before selecting equipment

### WAN traffic and cellular budget

With separate authorization, inventory available gateway WAN counters and their
definitions. Measure at the internet boundary, separately for ingress (download)
and egress (upload). Prefer a production-specific boundary where available; if
the gateway mixes household, staging and production traffic, label that limitation
and obtain approval for a method that separates them without collecting payloads.

Record start/end timestamps, interface direction, byte units, sampling interval,
counter resets, missing samples and measurement coverage. Collect a representative
full billing month where possible, including normal operation, busy periods,
scheduled jobs and recovery traffic. A shorter sample must be labeled an estimate,
with its duration and uncertainty; never present extrapolation as a measured month.

Report separately for each direction:

- Normal rate (median and 95th percentile), maximum sampled rate and its interval;
  identify brief bursts that coarse samples may miss.
- Daily and monthly totals in decimal GB (`bytes / 1,000,000,000`), plus the combined
  total and the carrier's actual billing definition.
- Full production versus the proposed critical-service-only profile; account for
  tunnel overhead, retries, reconnects, updates, image pulls, backups and telemetry.

Compute rate from reset-aware byte deltas divided by elapsed seconds; multiply by
eight for bits per second. Do not sum counters at several layers of the same path.
For planning, estimate outage GB from the measured critical-profile byte rate and
the selected outage duration, with explicit allowance for bursts and recovery.
Compare this against the remaining monthly allowance and the approved cost ceiling.

Existing Prometheus history may contain `node_network_receive_bytes_total` and
`node_network_transmit_bytes_total`. Confirm availability, retention, resets and
gaps before interpreting it. These node counters include LAN traffic such as
replication and service calls, and may count virtual interfaces or the same traffic
multiple times. They **cannot substitute for measured WAN usage**. Use them only
as supporting workload context, not a cellular plan sizing total.

### Critical-service policy and carrier qualification

The owner must approve a named service list, service dependencies and minimum
acceptable behavior. Candidate policy: retain required production ingress, tunnel,
DNS and essential monitoring; defer staging, nonessential batch work, bulk backups,
image updates and other discretionary transfers. This is a proposal, not a deployed
filter or permission to interrupt jobs. Include durable queues, postponed work and
catch-up traffic in the recovery plan. Define alert thresholds, a data reserve,
behavior near the cap, and who can authorize more spend or reduced service.

Before selecting a carrier or gateway, verify the actual plan's data cap, billing
cycle, overage, throttling, deprioritization, tethering/router restrictions and
whether both traffic directions count. Measure reception, loss, latency, upload
and download capacity at the intended placement under normal and busy conditions.
Record congestion and shared outage risks; a working cellular link today does not
prove the tower will survive the same utility outage.

Check CGNAT, IPv4/IPv6 behavior, DNS and supported outbound tunnel transports on
the candidate path. The repository's outbound tunnel design avoids relying on
direct inbound port forwarding, but CGNAT and carrier restrictions still require
an end-to-end test. Do not promise compatibility or introduce firewall, credential
or security changes as part of this document.

### Actual wall power and runtime

Measure actual AC wall power with a suitable meter for each required device and
the complete proposed outage load, including adapters, switches, storage and
cooling. Capture idle, normal critical workload, peak load, boot/recovery peaks and
sustained energy use over a stated interval. Avoid double-counting PoE devices
already included in a switch's input measurement. Nameplate ratings and the solar
guide's examples are not measured consumption.

The owner must choose the required runtime and safe shutdown reserve **before UPS
sizing**. Record acceptable service loss, shutdown/restart responsibilities, battery
aging margin and recharge expectations during repeated outages. Only then compare
candidate UPS runtime curves at the measured load, continuous and surge ratings,
usable energy, conversion losses, transfer behavior and installed supply support.

For an initial energy estimate, use `load_W * runtime_hours` as required delivered
energy, then account explicitly for conversion efficiency, usable battery fraction
and aging/reserve margins without counting a margin twice. Validate against vendor
runtime data and a controlled measured run; watt-hour arithmetic alone does not
establish runtime or compatibility. No battery capacity or product is selected yet.

## Controlled validation and human gates

1. **Design gate:** review a sanitized physical dependency map, the critical-service
   list, WAN measurements, power measurements, runtime target, budget and unresolved
   assumptions. Confirm that staging is unnecessary for production quorum, storage,
   DNS, routing, ingress and tunnel recovery. Separately approve any purchases or
   implementation; this draft provides neither approval.
2. **Test gate:** approve a bounded maintenance window, an on-site operator, a known
   restoration procedure and maximum outage, data-use and battery-discharge limits.
   Choose numeric recovery objectives and pass/fail thresholds before testing.
   Start with a bench or isolated test where feasible. Do not disconnect production
   power or networking, access hosts, or alter equipment under this docs-only task.
3. **Connectivity tests:** with future approval, establish a baseline using external
   synthetic checks and local service health, then test fiber failure, router loss,
   and cellular operation individually. Measure detection, route selection, tunnel
   reconnection and first sustained successful critical-service response separately.
   Check both new and existing sessions, DNS, ingress, origin reachability and data
   accounting. Verify the selected manual or automatic handoff and any required
   wireless path. A ready tunnel alone is not proof of an available application.
4. **Power tests:** test the approved full battery boundary under the critical load,
   then the combined power-plus-fiber failure. Demonstrate operation with staging
   absent and with any primary-only gateway/router absent if its UPS is deferred.
   Record runtime, peak draw, battery state and service health without an uncontrolled
   deep discharge. Stop on instability, overheating, unexpected load, loss of the
   recovery route, or any agreed time/data/battery limit.
5. **Recovery tests:** define failover detection and timeout, then require a stable
   primary path for an agreed hold-down period before failback. Test intermittent
   primary recovery to avoid repeated switching. Measure tunnel and application
   recovery on both transitions and after a controlled restart. Verify DHCP lease
   renewal and changed-address recovery, mDNS discovery and upstream DNS resolution,
   clock synchronization, existing credential availability and whether cached
   images/configuration allow recovery without an unexpected large download.
6. **Acceptance gate:** the human owner reviews measured results against the chosen
   objectives, confirms restoration and postponed-work handling, and explicitly
   accepts remaining single points of failure. Failed or untested cases remain
   open; implementation or broader work requires separate authorization.

Keep only sanitized aggregate evidence in this repository: method, interval,
coverage, units, result, uncertainty and pass/fail against approved objectives.
Do not publish home identifiers, addresses, SSIDs, device identifiers, private
traffic, payloads, itineraries, credentials or raw logs containing them. The public
design should explain dependencies without exposing the private physical map.
