# Outage report: Ethernet DHCP changes and control-plane recovery

**Record date:** 2026-10-16 (UTC; retrospective written after recovery)

**Observed incident date:** 2026-10-15 UTC / 2026-10-14 Pacific

**Component:** K3s embedded etcd membership, runtime networking, and Node address convergence

**Severity:** Critical; staging and production control planes affected

**Status:** Service recovery observed; durable prevention and recovery qualification open

**Incident owner:** [futuroptimist](https://github.com/futuroptimist)

## Summary and impact

After Ethernet DHCP addresses changed, both three-server clusters retained obsolete numeric
etcd peer endpoints and join configuration. Staging comprised `sugarkube3/4/5` running
K3s `v1.35.4+k3s1`; production comprised `sugarkube0/1/2` running `v1.34.5+k3s1`.
The staging API was unavailable during repeated elections. Production later showed the same
address drift and services stuck activating. Exact onset and total user-impact duration remain
unknown. Recovery checks establish short successful observation windows, not continuous availability.

Hostname discovery remained usable: the owner could reach staging through `.local` names.
That did not update persisted numeric etcd membership. A second failure layer remained after
supported Ethernet configuration was present: obsolete Node status addresses coincided with
network-policy-controller startup failures. Static address assignment is intentionally not the
durable solution. Wi-Fi failover is outside this incident's recovery scope.

The owner reported recovery using existing databases, cold backups, one seed per cluster,
and sequential peer rejoin. There is no evidence of a scheduled-snapshot restore or destructive
rebuild. These observations do not establish zero data loss or a completed restore test.

## Evidence and its limits

This report summarizes sanitized owner command transcripts and explicitly identified owner
reports. It does not publish raw logs, private discussion links, address values, or credentials.
The retained diagnostics support the timeline below. Complete commands and outputs for every
backup, reset, and rejoin operation were not retained in the supplied evidence.

Reports of power and WAN disruptions on October 12/13 provide context. Their alert clocks are
separate from the recovery timeline; they do not prove one continuous outage, its start time,
or a utility-provider root cause. The [May staging incident](2026-05-18-sugarkube-ha-staging-dhcp-ip-reassignment.md)
is historical context; its wipe/rebuild procedure was not the October recovery.
The [DSPACE report](https://github.com/democratizedspace/dspace/blob/main/outages/2026-07-23-dspace-production-version-drift.md)
provided editorial precedent for tracked follow-ups, not evidence about this incident.

## Timeline

All times in this table are **October 15 UTC**, seven hours ahead of **October 14 Pacific**.

| UTC | Pacific | Evidence and interpretation |
| --- | --- | --- |
| 03:33–03:45 | 20:33–20:45 | Staging retained obsolete numeric peer endpoints. All three recorded commit index `53334607`; old peer connections failed, elections repeated, and API was unavailable. `.local` access worked. Equal indexes alone do not establish database integrity or seed freshness. |
| 04:06–04:10 | 21:06–21:10 | The staging seed had supported YAML `node-ip` and `flannel-iface: eth0`, but repeatedly stopped with network-policy-controller error `failed to find interface with specified node ip`. |
| 04:20:45–04:20:54 | 21:20:45–21:20:54 | Staging node4 was promoted after rejoin, then hit a similar interface failure. Its annotation had the current address while Node status InternalIP remained obsolete. Promotion alone was not successful recovery. |
| 04:26:35–04:27:38 | 21:26:35–21:27:38 | Four staging checks succeeded: three Ready nodes, three voters, fresh advancing leases. Node5 status converged to its current address. This is a short stability window. |
| 04:29 | 21:29 | Production audit found changed Ethernet addresses, obsolete numeric join/peer endpoints and old SANs, and activating services. All three recorded commit index `69212322`; equality is not complete integrity evidence. |
| 04:57:14–04:58:16 | 21:57:14–21:58:16 | Four production checks succeeded: current addresses, three Ready nodes and voters, advancing leases, active services, and unchanged restart counts `7/7/3`. |
| Approximately 05:01 | Approximately 22:01 | Conversation-timed evidence showed ready workloads/running containers, ordinary completed Helm jobs, and a Bound 128 GiB Prometheus PVC. The owner reported danielsmith.io, token.place chat, Grafana, and watchdog working. Independent monitoring freshness and application data reconciliation remain unproven. |

## Failure analysis

1. **Discovery and durable membership are separate.** Successful mDNS lookup or remote access
   does not rewrite numeric peer URLs stored in etcd or obsolete server join URLs. Repeated
   elections and failed connections to old addresses explain loss of control-plane availability.
   Old SANs were also observed; their presence alone does not prove a certificate failure caused
   every unavailable endpoint.
2. **Generated settings must reach the running binary.** The repository helper generated
   environment-based node IP/Flannel settings. The exact incident versions' CLI definitions
   expose `node-ip` and `flannel-iface` without corresponding environment bindings. Environment
   presence is therefore insufficient evidence of effective runtime configuration. See
   [staging source](https://github.com/k3s-io/k3s/blob/v1.35.4%2Bk3s1/pkg/cli/cmds/agent.go)
   and [production source](https://github.com/k3s-io/k3s/blob/v1.34.5%2Bk3s1/pkg/cli/cmds/agent.go).
3. **Correct configuration did not immediately correct Node status.** The retained evidence
   shows startup loops even after supported YAML was installed, and disagreement between
   annotation and status on a rejoining peer. K3s's
   [network-policy integration](https://github.com/k3s-io/k3s/blob/v1.35.4%2Bk3s1/pkg/agent/netpol/netpol.go)
   uses kube-router components. This source supports the integration attribution, but the supplied
   diagnostics do not identify every internal call or prove a single upstream defect.

## Recovery performed, as reported by the owner

The owner reported readable, hashed cold backups; a single-seed membership reset using each
cluster's existing database; preservation of peer databases before sequential rejoin; supported
Ethernet YAML; and a guarded correction of the seed's Node status address. Peer status addresses
self-corrected. Full command provenance for those operations is incomplete, so the command
examples in the [golden recovery runbook](../docs/runbook.md#ethernet-dhcp-and-embedded-etcd-recovery)
are proposed reproducible procedures, not a reconstruction of commands known to have run.

The retained checks support recovered control planes and the reported application availability.
They do not prove all acknowledged writes survived, that volume contents were restored, that
monitoring independently detected recovery, or that another DHCP event would recover safely.

## Corrective work and acceptance

| Follow-up | Required outcome |
| --- | --- |
| [#2915: effective runtime configuration](https://github.com/futuroptimist/sugarkube/issues/2915) | Verify supported node IP and Flannel settings reach the exact running version, including precedence and restart behavior. |
| [#2916: state-preserving Ethernet DHCP recovery](https://github.com/futuroptimist/sugarkube/issues/2916) | Qualify address churn without static IP dependence, data erasure, or Wi-Fi assumptions. |
| [#2917: stale Node InternalIP loops](https://github.com/futuroptimist/sugarkube/issues/2917) | Bound convergence and recovery of status/config disagreement; cover seed and peers. |
| [#2918: independent monitoring verification](https://github.com/futuroptimist/sugarkube/issues/2918) | Verify fresh scrapes, alert clocks, watchdog behavior, and external application probes separately. |
| [#2919: backup, restore, and lost-quorum qualification](https://github.com/futuroptimist/sugarkube/issues/2919) | Demonstrate readable backups plus isolated restore/data validation and operator-controlled all-node recovery. |

[PR #2914](https://github.com/futuroptimist/sugarkube/pull/2914) is a separate draft implementation
at `0055eecc` with green CI at the time of this report. Its startup refresh and opt-in recovery
of one member with two surviving healthy members do not resolve all-node lost quorum or persistent
stale Node status. No live qualification or rollout has occurred.
Closed [#2403](https://github.com/futuroptimist/sugarkube/issues/2403) and
[#2407](https://github.com/futuroptimist/sugarkube/issues/2407) are foundations, not open dependencies.

Closure requires the runbook's separate acceptance checks for API readiness, membership and
voters, address convergence, leases, bounded restarts, pod networking, workloads, monitoring
freshness, applications, and data validation. Ready nodes, a Bound PVC, equal commit indexes,
and backup filenames are useful signals, but none proves successful restore or complete integrity.
