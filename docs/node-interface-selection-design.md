# K341: node Ethernet and Wi-Fi interface selection

Status: P2 design proposal for owner review; documentation only. No interface
controller, live qualification, rollout or automatic recovery guarantee exists.

## Scope and preserved invariants

Define a possible Ethernet-preferred node connectivity policy for two separate
three-server HA clusters: staging and production. Preserve each original etcd
cluster ID, all three member IDs and databases, Kubernetes Node names and UIDs,
and the existing cluster trust boundary. Do not replace servers with agents or
combine the clusters. A successful transition must preserve quorum and validate
application data separately from availability.

The owner reports that both clusters currently share an unmanaged PoE switch.
That is a common data and power failure domain. Wi-Fi cannot rescue an unpowered
Pi; an access point whose power or uplink uses that switch may fail with it.
Do not unplug the shared switch, change its uplink, restart shared DHCP/router/AP
services, or interrupt production to test staging. No VLAN isolation or independent
power path is established by the word "staging".

This document authorizes no implementation, live access, network/security or
credential changes, hardware purchases, reset, merge or deployment. It proposes
future offline tests and separately approved owner-run qualification. Static IPs
and DHCP reservations are not prerequisites; dynamic DHCP remains intentional.
The older [network setup](network_setup.md) reservation advice is not this design's
acceptance criterion.

## Relationship to existing work

| Layer | Existing work | K341 boundary |
| --- | --- | --- |
| Power and upstream WAN | Merged [PR #2913](https://github.com/futuroptimist/sugarkube/pull/2913), [power/network design](production-power-network-reliability.md) | Cellular and battery sustain the complete service path; changing a node interface does not select a carrier or power a failed switch |
| Ethernet address recovery | Draft [PR #2914](https://github.com/futuroptimist/sugarkube/pull/2914), reviewed here at `0055eecc5c1ee15ebb2b69dcb24e05657db9499f` | Supported startup configuration and guarded recovery of one existing Ethernet member with two healthy survivors; not merged, not Wi-Fi support, not lost-quorum recovery |
| Node interface selection | This proposal | Observe both LAN paths, qualify a candidate and coordinate address, discovery and runtime convergence without changing identity |
| Incident recovery | [October DHCP postmortem](../outages/2026-10-16-ethernet-dhcp-control-plane-recovery.md) and [recovery runbook](runbook.md#ethernet-dhcp-and-embedded-etcd-recovery) | Historical recovery is not an automatic interface-switch procedure |

Current main's `scripts/configure_k3s_node_ip.sh` and `scripts/k3s-discover.sh`
default discovery/address selection to `eth0` via `SUGARKUBE_MDNS_INTERFACE`.
Changing that variable or a default route alone is not a coordinated transition.
The postmortem records usable `.local` discovery while persisted numeric etcd
endpoints were stale, followed by stale Node InternalIP startup loops. PR #2914
addresses a separate subset of those problems; K341 must not silently extend or
compete with its recovery controller. Future integration needs a single transition
owner and incident journal shared with any authorized address-recovery mechanism.

## Evidence required before choosing an implementation

The incident recorded staging `v1.35.4+k3s1` and production `v1.34.5+k3s1`.
These are historical observations, not a current version inventory. Qualify both
exact installed builds independently; record embedded etcd, kernel, OS, CNI,
network-policy, resolver and Avahi versions and effective configuration.

| Unknown | Required evidence and consequence |
| --- | --- |
| Node hardware and radios | Board/radio/driver/firmware, antenna placement, radio availability and power management; no assumption that every node can maintain both links |
| Access point and topology | Model/firmware, independent power and uplink, supported bands, capacity and wired-to-wireless peer reachability; a guest SSID or client isolation may permit internet but block the cluster |
| Network manager | Whether NetworkManager, systemd-networkd or another manager owns addresses, routes and DNS; exact version, profile precedence, DHCP client IDs, event ordering and restart persistence |
| Layer 2/3 layout | Same or separate subnets, routing, return paths, MTU and IPv4/IPv6 policy; no assumed bridge, bonding, mesh, multicast relay or same address on both NICs |
| Discovery | Avahi interface allow/deny lists, advertised records, resolver selection, cache expiry, multicast delivery across wired/wireless clients and duplicate-host handling |
| Cluster runtime | Supported node address/Flannel configuration, restart requirement, peer URL updates, TLS identity and SAN validation, Node status convergence and workload/storage dependencies |
| Shared failure domains | Sanitized power/cable/AP/DHCP map proving which tests can occur without touching production; absent proof, physical failure injection is blocked |

[Upstream K3s networking options](https://docs.k3s.io/networking/basic-network-options)
document an explicit Flannel interface override. They do not establish live
interface migration support for the deployed builds. Inspect the matching release
source and verify effective runtime settings, not merely environment variables.
The incident's exact-version evidence remains the starting point. Unknown or
unsupported capabilities block promotion of this design to implementation.

## Separate link, LAN and WAN observations

Every sample must carry interface, source address, address generation, timestamp,
probe result and freshness. Use bounded probes scoped to each candidate interface
and source address; a successful unbound probe may have used the other NIC.
Record unknown separately from failure, and invalidate evidence when a lease,
route, association or interface generation changes.

| Signal | What it establishes | What it does not establish |
| --- | --- | --- |
| Ethernet carrier or Wi-Fi association | Local physical/link attachment | DHCP success, peer reachability, quorum or WAN service |
| Valid usable DHCP address and routes | A candidate source and route configuration | Address uniqueness, correct return path or working peer services |
| LAN peer checks | Authenticated reachability of the expected cluster's peers over the candidate path, with return-path evidence | Quorum from ping alone, pod connectivity or external access |
| Quorum evidence | Fresh authenticated agreement on the original cluster and members, two healthy surviving voters with successful consensus-backed operations | Safety after stale evidence, a second member failure or partition |
| WAN checks | Separate DNS, outbound transport, tunnel and external application observations | A reason to change healthy etcd transport or evidence that the LAN is broken |

Candidate LAN qualification must include both other servers, correct cluster/member
identity, API and etcd transport, plus bidirectional pod/service networking. Test
return traffic and mixed Ethernet/Wi-Fi peers, not just node-to-gateway ping.
Do not use WAN failure alone to move cluster identities between interfaces. Keep
healthy Ethernet LAN transport when the ISP is down; report WAN degradation to
the separate #2913 policy. If Wi-Fi provides WAN but cannot reach cluster peers,
it is ineligible for cluster transport. A future egress-only policy would need
separate routing and dependency qualification.

## Proposed route preference and transition policy

Ethernet is preferred only while qualified for the required LAN role. Wi-Fi is a
candidate fallback, not an unconditional default on carrier loss. The network
manager must own route installation; a future coordinator must not race DHCP
hooks, discovery scripts or the Ethernet recovery controller.

Choose explicit unequal route preferences after inspecting the actual manager.
Default-route metrics alone do not select on-link peer routes, application-bound
sockets, Flannel or etcd advertisements. Validate source address selection, local
subnet routes, policy rules, return paths and both address families. Same-subnet
dual attachment needs qualification for ARP/neighbor behavior and asymmetric
routing. Do not propose bridging/bonding NICs or disabling security checks to
conceal a topology failure. Existing connections may break on address changes.

Before implementation, the owner must approve numeric values for probe interval,
probe timeout, maximum evidence age, consecutive failure/success counts, minimum
dwell time, longer Ethernet recovery hold-down, total transition deadline and
maximum attempts per incident. No production defaults are selected here. Use a
monotonic clock for hysteresis and a durable incident generation across process
restarts. Missing thresholds mean observe-only, not automatic selection.

| State | Entry/exit contract |
| --- | --- |
| Observe-only | Default until inventory, exact-version support and gates are approved; report separate link/LAN/WAN states without mutation |
| Ethernet qualified | Keep Ethernet while LAN checks pass, including during WAN outage; debounce loss using the approved failure window |
| Candidate Wi-Fi | Qualify address, discovery, trusted peers and data plane for the success window without withdrawing the current usable path; no promotion on association alone |
| Transition pending | One member per cluster, serialized ownership and fresh two-survivor quorum; revalidate immediately before every proposed mutation |
| Wi-Fi qualified | Complete runtime, membership, Node and application acceptance within deadline; preserve incident evidence and enforce dwell time |
| Ethernet recovery candidate | Require the longer stable hold-down plus all original qualification checks; use the same serialized transition gates for failback |
| Manual hold | No safe candidate, identity conflict, stale evidence, lost quorum, ambiguous operation or deadline exceeded; stop further mutations and retain evidence |

A proposed transition plan must name its old/new addresses, affected routes,
discovery records, effective runtime settings, peer endpoints, expected Node
status, validation and rollback prerequisites. Persist intent before changes and
outcome after each step. Ordering across those surfaces is an unresolved
exact-version integration task, not an atomic operation promised by this design.
If a candidate cannot be tested alongside the active path without changing cluster
behavior, it requires an isolated rehearsal before any owner-run transition.

Failback is a new guarded transition, not an unconditional restoration of saved
files. An old DHCP address may no longer belong to the node. Revalidate the old
path, current leases, peer endpoints and quorum before any rollback; otherwise
hold for the owner. On timeout after a possibly committed peer update, inspect the
actual committed state before deciding anything further. Never blindly replay it.

## DHCP, mDNS and durable identity

Treat renewal with the same address, changed lease, expiry, duplicate address,
multiple addresses, gateway/DNS changes and boot without a lease as distinct cases.
An expired or ambiguous address is ineligible. Address churn on either interface
invalidates its candidate evidence and starts a new generation; it must not reset
an incident's attempt limit. Do not reuse one NIC's lease on the other or assume
DHCP assigns the same address to both.

mDNS is a locator, not cluster membership or authentication. Following
[RFC 6762](https://www.rfc-editor.org/rfc/rfc6762), account for link-local scope,
multiple interfaces, record expiry and cache updates. Do not assume a `.local`
query crosses subnets. Qualification must independently exercise advertisement
and resolution: which interface publishes host and service records, which A/AAAA
addresses clients receive, and whether all intended peers can resolve and use them.
Test old cached answers, duplicate names, stale service records and loss of
multicast with working unicast. Keep discovery scope distinct from the selected
cluster transport; advertisements must not claim an unusable endpoint is ready.

A future design must specify record withdrawal/update and bounded cache convergence
with the exact Avahi/resolver configuration. During overlap, clients must validate
candidate addresses against trusted TLS and original cluster/member identity.
Do not accept the first `.local` answer as authority, bypass certificate validation,
change credentials, or automatically enable a multicast reflector. If valid
resolution cannot identify an authenticated reachable peer, hold rather than join
a new cluster. Unicast health and mDNS health must remain separate report fields.

The [etcd runtime reconfiguration guide](https://etcd.io/docs/v3.5/op-guide/runtime-configuration/)
distinguishes consensus-backed peer URL changes from local configuration. Use it
as conceptual background, not a claim that the embedded version has been qualified.
An interface/address change must preserve the existing member and database. Any
future endpoint-update procedure must demonstrate support on the exact embedded
version, live quorum, authenticated identity and serialized coordination first.
No automatic reset, member add/remove, force-new-cluster, database deletion,
restore, or replacement cluster is permitted by this selection policy.

Node names and UIDs remain stable; changing InternalIP is not creation of a new
Node. Check effective `node-ip`, `flannel-iface`, join/API endpoints, TLS validation,
etcd advertised/listening endpoints, Node annotations and status, leases, pod
routes and network-policy startup together. A route change or Ready node alone
is insufficient. Persistent stale Node status requires owner investigation;
automatic status patching, re-registration or restart loops are not a fallback.
The two clusters retain separate journals, trust material and qualification results.

## Partial connectivity and fail-closed behavior

| Observation | Required proposed outcome |
| --- | --- |
| Carrier up, Ethernet peers unreachable | Investigate LAN failure; consider only independently qualified Wi-Fi |
| Ethernet peers healthy, WAN unavailable | Retain cluster transport; report upstream degradation |
| Wi-Fi associated, no DHCP or isolated clients | Reject candidate, even if gateway or internet responds |
| mDNS works, numeric etcd endpoint stale | Address-recovery problem; discovery alone cannot authorize a start or update |
| Unicast works, multicast blocked | Report discovery failure; hold any transition requiring fresh discovery |
| One-way peer reachability or CNI failure | Reject candidate; API success does not establish workload connectivity |
| One server isolated, two original voters healthy | Preserve survivor quorum; only the isolated member may be considered after all gates |
| Two servers lost or simultaneous address drift | Stop automated transitions; preserve databases and require owner recovery |
| Different cluster/member identity or duplicate Node | Refuse candidate and preserve evidence; never auto-enroll or replace identity |
| Flapping paths, reboot mid-transition, uncertain RPC outcome | Durable manual hold; reconcile actual state, no reset of attempts or blind retry |
| Both paths fail or shared PoE removes power | Report unavailable/unknown through any already working channel; no self-healing claim |

Fail-closed means refusing further unsafe selection/recovery mutations, not
intentionally shutting down healthy voters or withdrawing their working routes.
Retain a verified usable path where possible. If the changed member cannot serve
safely, its separately approved transition procedure must define containment;
never stop another voter to make progress. No quorum means no automated endpoint
rewrite, cluster reset, bootstrap, or data erasure. Lack of an alert delivery path
must be visible as unknown, not a successful notification.

## Proposed offline tests (not implemented or executed here)

Use fake clocks, synthetic addresses, recorded sanitized fixtures and disposable
local test clusters with new test-only identities. No production kubeconfig,
credentials, host mounts, multicast on the household LAN or physical failure
injection belongs in these tests. A namespace/VM network must have no bridge or
route to either real cluster; prove that isolation before running protocol tests.

| Test group | Proposed evidence and assertions |
| --- | --- |
| State model | Exhaust state transitions, missing/stale samples, threshold boundaries, clock changes and event reorderings; no mutation without all gates |
| Hysteresis | Rapid carrier/association flaps, WAN-only outage, lease churn and recovery; bounded attempts, dwell and longer failback hold-down |
| Routing | Two NICs, same/different subnets, conflicting metrics, asymmetric return path, IPv4/IPv6 mismatch and MTU loss; prove probes use the intended source/path |
| DHCP | Same-address renewal, changed/expired lease, missing gateway/DNS and duplicate/multiple addresses; invalidate evidence without losing incident ownership |
| Discovery | Dual-interface advertisements, stale A/AAAA/service caches, blocked multicast and duplicate names; authenticate original peers rather than trusting answers |
| Identity/quorum | Disposable three-member etcd with one member moving; original IDs/data remain, both survivors commit, concurrent transitions denied; two-member loss holds |
| Crash boundaries | Crash before/after every journal/config/endpoint step, timeout after commit, stale lock and reboot; reconcile rather than repeat an uncertain mutation |
| Runtime/data plane | Exact K3s build in isolated VMs: effective settings, Node UID/InternalIP, CNI, policy, pod/service traffic and data checks; mocks cannot establish this result |
| Failback | Ethernet briefly returns then fails, old lease reassigned, original path unusable; no unconditional rollback or repeat restart |

A pure model pass proves decision logic only. Disposable etcd tests establish
protocol behavior only for their tested version. Neither qualifies radios, APs,
real network-manager integration, power independence or production service recovery.

## Separate owner-run qualification gates

1. **Inventory and design:** approve the sanitized dependency map, exact versions,
   transition ordering, ownership integration with #2914, thresholds, service/data
   acceptance criteria and remaining single points of failure. Resolve capability
   unknowns; prepare a separately reviewed implementation before live testing.
2. **Isolation:** use an independent bench first. Prove test power, AP, DHCP and
   switching cannot affect production. Because the present unmanaged PoE switch is
   shared, switch/power/AP failure injection is blocked until independent equipment
   or an explicitly approved production maintenance plan exists. This design grants
   neither equipment purchase nor that approval.
3. **Staging authorization:** owner approves the specific bounded window, one-member
   sequence, on-site operator, recovery access independent of the test path, readable
   backups, restoration procedure and stop limits. Keep three servers and prove two
   healthy survivors before each transition. No all-member switching rehearsal on
   shared infrastructure. Existing backup files alone do not prove restore.
4. **Staging measurement:** owner separately runs Ethernet loss, partial LAN failure,
   Wi-Fi loss, DHCP churn, discovery loss, WAN-only failure and stable/flapping
   failback cases. Measure detection, qualification, route/runtime convergence and
   sustained application recovery separately. Record unchanged cluster/member IDs,
   Node UIDs, quorum, leases, bounded restarts, pod/service traffic, TLS, monitoring
   freshness and application data checks. Stop on quorum loss, identity mismatch,
   production impact, loss of operator access, ambiguous mutation or any limit.
5. **Production authorization:** only after staging acceptance, independently review
   production's exact-version evidence, independent power/network dependencies and
   remaining risks. A separate owner approval and maintenance plan is required;
   staging success is not production authorization or proof of version parity.
6. **Acceptance:** retain sanitized method, versions, interval, coverage, thresholds,
   result and uncertainties for each case. All untested/failed cases remain open.
   Recovery objectives and any automatic behavior require measured evidence; this
   documentation PR does not close K341's implementation or qualification scope.

Do not publish SSIDs, addresses, device identifiers, private topology details,
credentials or raw traffic. Owner evidence may retain sensitive diagnostics in an
approved private location; public results should use synthetic identifiers and
aggregate measurements. No live operations were performed to prepare this design.
