# Ethernet DHCP recovery with data and quorum guards

K-339 remains open until owner-run staging and production qualification. This implementation
provides automatic local address refresh and an **optional, disabled-by-default recovery
controller**. Version 1 enrollment handles one changed server with two healthy survivors.
Version 2 adds experimental all-member transport recovery through pre-enrolled hostname
peer URLs. It is not qualified for rollout and cannot repair genuine loss of quorum data. Static IP assignments, DHCP reservations and Wi-Fi
failover are not solutions used by these tools.

No live staging or production access was used to develop this change. Earlier disposable
three-server, agentless K3s experiments established the dual-URL transport mechanism on both
exact versions. Those experiments do not validate this implementation. Its new three-server
test remains incomplete because of fixture/storage failures. Unit and protocol tests cannot
qualify Node status convergence, application availability or the deployed clusters.

## Why both numeric and hostname peer URLs matter

The K3s sources for both deployed versions define `NodeIPFlag` and `FlannelIfaceFlag` without
`EnvVars`. `K3S_NODE_IP` and `K3S_FLANNEL_IFACE` therefore do not configure those flags:

- [v1.35.4+k3s1 agent flags](https://github.com/k3s-io/k3s/blob/v1.35.4%2Bk3s1/pkg/cli/cmds/agent.go)
- [v1.34.5+k3s1 agent flags](https://github.com/k3s-io/k3s/blob/v1.34.5%2Bk3s1/pkg/cli/cmds/agent.go)

Use supported YAML `node-ip` and `flannel-iface`. A conflicting CLI option can override YAML;
configuration precedence must be verified before enrollment.

[K3s embedded etcd](https://github.com/k3s-io/k3s/blob/v1.35.4%2Bk3s1/pkg/etcd/etcd.go)
constructs its expected peer URL from `PrivateIP` and checks both member name and peer URL.
It checks every peer URL, so a hostname-only failure does not disprove dual URLs. A stable
hostname can restore peer transport from initialized databases before the API becomes ready;
consensus can then reconcile the numeric URL expected by K3s. Version 2 retains both URLs
and changes only the original local member's numeric URL. Discovery supplies untrusted
locators; mutual TLS and exact cluster/member IDs establish identity.

[K3s server configuration](https://github.com/k3s-io/k3s/blob/v1.35.4%2Bk3s1/pkg/cli/server/server.go)
adds current node IPs to SANs, and its
[certificate generator](https://github.com/k3s-io/k3s/blob/v1.35.4%2Bk3s1/pkg/daemons/control/deps/deps.go)
regenerates certificates when required SANs change. This source behavior still requires
qualification against both exact installed versions. The controller never edits certificates,
WAL, snapshots, tokens or database directories.

## Default preparation and every-start refresh

```bash
sudo -E bash scripts/configure_k3s_node_ip.sh
# Existing server: explicitly review quorum/backups before preparing changes.
sudo -E bash scripts/configure_k3s_node_ip.sh --prepare-server
```

Before persisting a literal address, preparation installs a managed helper copy and required
`ExecStartPre` drop-ins for `k3s.service` and `k3s-agent.service`. Every systemd start, including
an ordinary reboot after DHCP changes, refreshes `config.yaml.d/20-sugarkube-network.yaml`
from the current primary global Ethernet IPv4 address. The interface defaults to `eth0`;
`SUGARKUBE_MDNS_INTERFACE` selects another Ethernet interface during preparation.
Root installation refuses untrusted file ownership, writable or symlinked ancestry. Runtime
files and all directory entries are synced before either start hook is published, so an
interrupted installation cannot expose a durable hook with an unpersisted runtime prerequisite.

The pre-start command runs after `network-online.target`, has a 30-second timeout, and blocks
K3s execution if the address is missing, invalid or ambiguous, or the reserved YAML path is
unmanaged, a symlink or a directory. The installed hook owns that path and recreates an absent
file from the current address. This lets a reboot finish interrupted first preparation even
if a hook was published before YAML existed; no literal address is persisted before refresh
protection exists. A failed refresh preserves the old file but does not allow K3s to consume it
through this start path. It writes only owned network YAML; it cannot migrate legacy files,
rewrite TLS policy or mutate membership. The installed copy does not depend on the checkout.

The Ethernet helper and controller refresh now log to
`/var/lib/sugarkube/logs/configure_k3s_node_ip.log`. Ubuntu 24.04.5 qualification found
`/var/log` owned by UID 0, GID 102 with mode `0775`; the strict ancestor guard correctly
refused that group-writable path. The application state path avoids that ancestor without
changing system directory permissions or relaxing ownership, mode or symlink checks.
`SUGARKUBE_LOG_DIR` remains an explicit helper override and must satisfy the same guards;
there is no silent fallback for an unsafe override. Other scripts' logging is unchanged.

Existing logs are retained in place, without copying, deletion or automatic migration.
Previously installed hooks retain their explicit old argument until preparation updates them.
On an existing server, a reviewed `--prepare-server` run installs the updated helper and
managed hooks; load them only through a separately controlled daemon reload or reboot.
An already enrolled recovery installation fingerprints these files, so changing them invalidates
its enrollment and needs a separate reviewed migration. Do not delete enrollment or journals
to bypass that check. A fresh qualification guest whose preparation failed before K3s creation
can rerun preparation from the fixed revision, without a database reset. This fix is covered
by synthetic root filesystem tests; Ubuntu guest retesting and broader platform support
remain unproven until recorded. See the
[Ubuntu preparation finding](../outages/2026-10-17-ubuntu-network-log-path.json).

Preparation never reloads systemd or starts/restarts a service. The K3s installer loads the
new drop-ins on a fresh installation; an existing installation loads them after an operator
reload or reboot. Installing/upgrading the hook on an existing server requires explicit
`--prepare-server`. `just up` stops before discovery/install if preparation fails, including
hook installation failure. Tests cover this through the actual recipe.

Exact helper-owned legacy `10-node-ip.conf` files are retained as `.pre-yaml` backups.
Custom files and existing backups remain for operator review. Missing or contradictory
configuration is a stop condition. Do not remove required pre-start commands in later unit
files. The default helper alone does not repair etcd membership or trigger a running service
restart when DHCP changes.

## Opt-in automated path

`scripts/ethernet_quorum_recover.py` supports only three established embedded-etcd voters,
single-stack Ethernet IPv4, the two exact K3s versions above and the standard K3s paths.
It rejects CLI/environment/YAML network overrides, raw-IP join targets, alternate data/config
paths, custom server drop-ins, changed enrolled files or changed membership. Resolve these
conditions through a separate reviewed migration before enrolling.

The controller uses native authenticated gRPC on port 2379. Both exact K3s versions
reserve their HTTP/1 JSON listener on loopback port 2382; that listener is not exposed or
used by this controller. Official etcd protobuf schemas preserve uint64 identities and
repeated peer URLs. Each response must contain the enrolled cluster and endpoint member IDs.

The client pins each discovered IP to the existing Ethernet-interface and source-address
bound TCP connection. grpcio verifies the enrolled DNS hostname, server CA and mutual TLS
client credentials. A mode-0700 temporary directory holds a private Unix socket that accepts
once and forwards encrypted bytes to that one TCP connection. It does not terminate TLS.
RPC retries are disabled; no second outbound connection is possible through the relay.
Connection, TLS, RPC or identity failures close and latch the session. A failed mutation
can have an unknown outcome; neither the client nor watcher automatically replays it.
An authenticated false transaction comparison is returned explicitly as false, separately
from an unknown outcome. Version 1 latches competing incident ownership; version 2 waits only after an authenticated,
definitive false comparison, without taking over another incident.

Quorum proof uses linearizable reads; a TCP connection, mDNS answer, cached membership or
API readiness is insufficient. The transport tests use an actual mutual-TLS gRPC server
with synthetic identities and the existing disposable-etcd tests. They do not qualify
three-member recovery. The version 2 implementation below includes the resolver, healthy-time
dual-URL enrollment, existing-database startup and separate membership/completion phases.
Their combined deployment and recovery behavior remains unqualified.

### Version 1 enrollment while healthy

Enrollment is an explicit owner operation after verified backups and a recovery drill. It
requires all three voters healthy, current peer URLs, matching Node UIDs/member annotations,
and converged Node addresses. It records the machine identity, original address, exact K3s
version, effective systemd settings, YAML files, environment files and trust-root hashes. Native etcd/API client certificate
renewal is allowed at the same protected paths; CA and configuration changes invalidate
enrollment. Only a standard inline-certificate kubeconfig is accepted, with no exec plugins
or token/file credential overrides.
The original address is a baseline for detecting changes, not a static assignment.

`python3-yaml`, `python3-grpcio`, `python3-protobuf` and `python3-dnslib` are installed by
`scripts/install_deps.sh`. Enrollment installs the transport module and verified wire schema
before publishing the start hook. The schema provenance and Apache license are under
`scripts/vendor/etcd`; its generator verifies the exact source and output hashes. Standard K3s `kubectl`, Avahi,
`ip`, systemd and Python must be available. Prepare the default boot hook first, then create
a root-owned mode-0600 request using **verified actual decimal IDs and exact names**:

```json
{
  "schema_version": 1,
  "k3s_version": "v1.35.4+k3s1",
  "interface": "eth0",
  "cluster_id": "123456789",
  "local_member_id": "101",
  "verified_backup": true,
  "members": [
    {"id": "101", "name": "pi0-existing-member-name", "hostname": "pi0.local", "node_uid": "actual-uid-0"},
    {"id": "102", "name": "pi1-existing-member-name", "hostname": "pi1.local", "node_uid": "actual-uid-1"},
    {"id": "103", "name": "pi2-existing-member-name", "hostname": "pi2.local", "node_uid": "actual-uid-2"}
  ],
  "etcd_tls": {
    "ca": "/var/lib/rancher/k3s/server/tls/etcd/server-ca.crt",
    "cert": "/var/lib/rancher/k3s/server/tls/etcd/client.crt",
    "key": "/var/lib/rancher/k3s/server/tls/etcd/client.key"
  },
  "kubeconfig": "/etc/rancher/k3s/k3s.yaml"
}
```

The values above are placeholders. Do not infer member IDs from node names or reuse IDs
across staging and production. The backup flag is an operator attestation, not an automatic
backup integrity check. Keep the request, enrollment and credentials out of PR logs.

```bash
sudo python3 scripts/ethernet_quorum_recover.py enroll \
  --request /root/sugarkube-recovery-request.json
```

This installs the enrolled controller, a server pre-start/post-start drop-in, and the
`sugarkube-ethernet-recovery.service`/`.timer` units. It **does not reload, enable or start**
anything. Existing enrollment or hook files are refused rather than overwritten. Failed
installation remains disabled and requires inspection before retrying. The owner must
explicitly load and enable these units as part of the staging qualification below.

### Version 1 address-change state machine

1. The timer observes every 30 seconds. A new address must remain observed for at least
   30 seconds before it acts on a running server. Boot/start recovery can act directly after
   required address refresh. Unchanged voters may cold-start without an existing quorum;
   otherwise an ordinary cluster power-up would deadlock.
2. Authenticate both other enrolled voters, verify their identities and quorum, and check
   unchanged three-member voting membership plus the local Node UID/member binding.
3. Persist a local journal and acquire a cluster-wide incident record with etcd compare-and-swap.
   There is no expiring lease or automatic takeover. Only one incident may own recovery.
4. For the running-server path, refresh owned network YAML. Revalidate the address, identities,
   quorum, configuration and membership immediately before updating only the local member's
   peer URL. Read membership back and require exact confirmation with unchanged survivor records.
5. Durably authorize one start. The watcher releases its local lock before queuing one local
   `try-restart`; the pre-start hook consumes that authorization. A boot-triggered repair permits
   the already requested start. K3s's `Restart=always` cannot replay an unfinished authorization
   and repeatedly execute K3s. Failed pre-start jobs can still be retried by systemd.
6. Completion requires all three voters healthy, the same local Node Ready with current
   annotation/status InternalIP, and the same active K3s process/invocation/restart count across
   a 30-second verification window. Only then is incident ownership released. Post-start failure
   does not kill a healthy process; the timer can retry completion without repeating mutation.

A failed/ambiguous membership RPC leaves the incident latched. No blind retry, member removal,
member addition, identity regeneration, database replacement, reset or peer rejoin is issued.
A second address change, lost quorum, changed identity, configuration drift or restart during
verification stops the incident. No software can guarantee that a second independent voter
will not fail after a successful quorum check; the response is to preserve state and stop.

Manual maintenance must disable the timer and coordinate with the persistent incident owner.
Do not delete the incident key or journal to force progress. A separate KV lock cannot
atomically fence an unrelated membership RPC; automatic lease takeover is intentionally absent.

### Version 1 stale Node status and explicit resumption

The controller does not patch Node status automatically. A current `k3s.io/internal-ip`
annotation with stale `status.addresses` can still cause the observed network-controller
restart failure. That is a remaining limit on unattended recovery.

Use the read-only planner below to review a status-subresource-only JSON Patch guarded by
Node UID, resourceVersion and the previous addresses. Recollect evidence on a conflict.
Preserve other address types. Never strip the patch tests or guess a Node identity.

After investigation and any required guarded status repair, an operator can explicitly request
one further start with `resume`. It verifies both survivors, ownership, current member URL,
configuration and Node binding. It accepts converged addresses or the consistent old address
pair before a first start; contradictory annotation/status requires reconciliation first.
It records the operator resumption and never repeats the membership update.

```bash
sudo python3 /usr/local/libexec/sugarkube/ethernet-quorum-recover.py resume
```

This is a service-changing operator command, not a read-only diagnostic. Do not run it during
normal observation or without reviewing the latched incident and backups. If membership does
not match the new address, reconcile the unknown outcome explicitly before resuming.

## Experimental version 2 all-member recovery

This mode requires three existing voters, exact enrolled identities and versions, unique
`.local` hostnames, single-stack Ethernet IPv4, standard database paths and healthy-time
preparation. It is disabled until explicitly armed on each server. Existing version 1
enrollment is not silently upgraded. Installation refuses existing files, so migration needs
a separate reviewed procedure rather than deleting enrollment or incident records.

### Resolver and certificate prerequisites

Every server's normal K3s certificate configuration must already include its own unique
enrolled hostname. Healthy enrollment verifies peer TLS on port 2380, including the actual
peer source-address SAN check, and rejects another enrolled hostname in that certificate.
No controller command provisions, edits or disables certificates. Native K3s renewal must
retain the hostname when it adds the new numeric address. Certificate renewal on the exact
Pi installation remains part of qualification.

The resolver listens on loopback port 53 at `127.0.0.55`. It queries mDNS directly through the
enrolled Ethernet interface, accepts only the three enrolled names and current-subnet IPv4
answers, and fails closed on observed conflicting answers or withdrawals. It has bounded
queries, packets and workers; it does not cache discovery. A single false answer can still
be an untrusted locator: TLS and exact member identity must reject it before mutation.
Observation of one answer does not prove that no unseen conflicting responder exists.

A K3s service mount gives that process the scoped resolver without changing host DNS.
Other DNS queries retain the host's upstream servers; unknown `.local` names are refused.
Kubelet uses a separate copy of an existing valid pod resolver source. Preparation refuses
to invent a public DNS fallback. Search/options changes require an owner-controlled K3s
restart; configuration checks block recovery if the running process sees a stale resolver
view. The systemd mount and actual pod DNS behavior have not been qualified in this cloud.

### Healthy-time sequence

Use the request above with `schema_version` set to `2` and add `completion_https_urls`, an
array of explicit application HTTPS health URLs such as `https://app.example/health`.
These are real owner-chosen workload checks, not Kubernetes or etcd control-plane ports.
Normal CA verification is required; embedded credentials and numeric hosts are rejected.

With verified backups, all three original voters and Nodes healthy, and the default network
hook prepared, the intended sequence is:

1. Run `prepare-resolver --request /root/sugarkube-recovery-request.json` from the checkout
   controller. It installs inactive resolver files only. Review and activate them one server
   at a time, checking DNS, TLS, pod DNS and quorum between rolling restarts.
2. Run `enroll --request /root/sugarkube-recovery-request.json` on each server. This captures
   trusted files and immutable local WAL identity headers, then installs inactive recovery
   hooks. Load the units only after reviewing the complete installation.
3. Run the installed controller's `enroll-peer` on each server in turn. Each operation proves
   all three healthy identities, acquires the persistent membership lock, adds only its own
   hostname alongside its existing numeric peer URL, confirms consensus readback, releases
   the lock and records its enrollment marker.
4. Run `arm` on each server. Arming requires all three current dual peer URLs, exact enrollment
   markers, healthy Nodes and peer TLS. Enable the watcher only after the representative
   qualification below passes. No preparation command reloads or enables systemd units.

The installed controller path is `/usr/local/libexec/sugarkube/ethernet-quorum-recover.py`.
For example, `sudo python3 /usr/local/libexec/sugarkube/ethernet-quorum-recover.py arm` is an
explicit state-changing owner operation, not a diagnostic. Do not run this sequence on live
clusters based on the present cloud evidence.

### Transport, membership and completion

On a cold address change, each server validates its trusted configuration, enrolled database
identity, stable Ethernet address and own mDNS locator before authorizing one existing-database
start. It does not wait for another healthy voter or the API. A running server debounces the
change, refreshes owned network YAML and records one restart authorization to rebind transport.
No database is initialized or replaced by the controller. The WAL checker reads only bounded,
CRC-validated immutable identity headers; K3s still validates and opens its own database.

After hostname transport restores consensus, the controller authenticates all three original
members and performs linearizable checks before acquiring the membership lock. It records
durable mutation intent, changes only its own numeric URL while retaining its hostname,
verifies readback and releases the lock. API readiness is deliberately checked afterwards,
so one server waiting for Node status cannot prevent the others repairing their numeric URLs.

Local completion still requires all three healthy voters, original Node UIDs and member
bindings, current annotation/status addresses, Node Ready, ready workload controllers and
pods, application HTTPS success, and a stable K3s process over 30 seconds. Stale Node status
or failed workloads leave completion pending; they are never patched or reported recovered.

A definitive false acquisition comparison permits automatic waiting. If another original
member completes between the membership snapshot and successful acquisition, the controller
re-proves all identities and health, requires its own record unchanged and each changed peer's
URLs to match its current enrolled hostname and discovered address, then releases only its
exact ownership with guarded compare-and-swap. A confirmed release permits waiting and fresh
proof on a later invocation; it never dispatches a membership update in that invocation.
False or unknown release results stay latched in a distinct pre-mutation release phase,
including under explicit `resume`, and require operator reconciliation. Unexpected membership
changes also remain latched. Unknown acquisition, MemberUpdate or release outcomes remain latched. Explicit `resume` authenticates consensus
state and reads back the recorded intent; it does not replay an unknown MemberUpdate.
`resume-transport` permits one reviewed restart of the original database while retaining
unknown membership intent. `resume-peer-enrollment` performs explicit enrollment readback.
These commands cannot take over another owner's lock, remove members or bypass identity
checks. A second address change or contradictory state stops progress for operator review.

### Evidence and acceptance boundary

Unit tests cover all-three startup without quorum, reconciliation before API availability,
lock release before completion, definite contention, unknown RPC outcomes, stale status,
workload failures and identity drift. Resolver tests include real isolated multicast discovery,
conflicting answers, withdrawal, ordinary DNS and TCP queries. Transport tests use actual
mutual TLS and native gRPC; read-only WAL fixtures come from both exact K3s versions.

The earlier architecture experiment used actual three-server agentless K3s on both versions
and preserved identities, committed markers and API objects after cold/running churn. The
new implementation test did not reach three-server enrollment: storage became critically
low and a joining fixture logged a numeric-address TLS verification failure. No end-to-end
pass is claimed for the new code. Normal K3s agents additionally require writable cgroup
capabilities unavailable here; privileges were not expanded. Systemd, kubelet, CNI, real Node
status, application recovery and native Pi behavior remain acceptance blockers.

Before rollout, repeat both cold and running all-member address changes on representative
three-server staging, preserving IDs, databases and committed workload data. Include stale
Node status, partitions, reused addresses, false discovery and interrupted recovery. Verify
certificate renewal and completion, not merely etcd quorum or API readiness. Staging and
production share an unmanaged PoE switch: use isolated staging networking or changes scoped
to staging nodes. Do not cycle the shared switch, change shared router DHCP settings or
interrupt production to create the staging drill.

## Read-only evidence planner

```bash
python3 scripts/ethernet_recovery_plan.py /secure/path/evidence.json
python3 scripts/ethernet_recovery_plan.py --resolve-mdns /secure/path/evidence.json
```

The planner never applies changes. Optional Avahi discovery is bounded to three hostnames and
five seconds per hostname; it preserves the capture timestamp. The evidence must be no more
than 300 seconds old. Offline health records are operator-supplied and cannot be authenticated
by this planner. See [regression fixtures](../tests/test_ethernet_recovery_plan.py) for the full
schema: cluster/member IDs, three voter records, authenticated health evidence, mDNS and local
Ethernet observations, effective join targets and captured Kubernetes Node objects.

- `no-change`: no address change identified in supplied evidence; not a full health attestation.
- `live-quorum-review`: two proven survivors permit review of a changed member's peer URL,
  join targets and guarded status patch candidates. Candidates are not execution authorization.
- `operator-intervention`: insufficient or contradictory evidence; no mutation candidates.
  Failure to prove quorum does not establish permanent quorum loss.

## Genuine quorum loss

Neither mode can commit membership changes without consensus or choose an authoritative
replacement database. Version 2 restores transport only between the three original databases
using hostname URLs enrolled before the outage. It does not repair missing or corrupt data,
removed members, absent enrollment or conflicting identities. Preserve all databases,
tokens, journals and configuration for separately authorized operator recovery. These tools
do not reset membership, replace identities or generate reset/deletion commands.

## Owner-run qualification and rollout gate

**K-339 is not Done on CI success or merge.** Do not enable the controller in production on
unit tests or disposable etcd evidence alone. The owner must record these results and accept
the remaining limitations. Planned production downtime is allowed after staging passes;
later second-cluster/load-balancer work is not a prerequisite.

1. Establish a maintenance window and console access independent of the affected LAN address.
   Capture exact K3s versions, all member/cluster IDs, Node UIDs, peer URLs, effective settings,
   current Ethernet addresses, Node annotations/status, service restarts and workload health.
2. Obtain a verified etcd snapshot plus cold copies, preserving tokens and full DB directories.
   Stop/copy/restart one server at a time, keeping two proven healthy voters. Verify restoration
   in an isolated environment that cannot contact the original cluster. Record a persistent
   workload marker and digest and confirm normal reads/writes before proceeding.
3. Qualify both exact K3s versions in staging or an isolated representative K3s environment.
   Prepare/enroll while healthy. Inspect installed units, then explicitly reload systemd and
   enable the timer for this owner-controlled test. Do not enable an incomplete installation.
4. Change one member's Ethernet lease through normal DHCP. For the boot path, reboot normally
   without rerunning preparation and verify the installed pre-start loads the new address.
   For the watcher path, leave K3s running and observe debounce, authenticated quorum proof,
   one member update and one restart. Keep both other voters unchanged and healthy.
5. Verify the same three member IDs and Node UIDs, current IP peer URLs, all proposal-health
   checks, Node Ready and matching annotation/status, stable restart counts and preserved/new
   workload writes. Confirm incident release only after the verification window.
6. Exercise missing/ambiguous addressing, failed preparation, wrong mDNS identity, config drift,
   stale status, a failed/ambiguous update and repeated invocations. Require no install on
   preparation failure, no unproven mutation, no repeat restart and preserved databases. An
   injected stale-status case needs an owner-reviewed procedure and guarded restoration.
7. Stop on loss of a second voter, identity/TLS mismatch, changed data marker, unexpected member
   replacement or restart loop. Disable automation, preserve diagnostics and all databases,
   and follow explicit recovery. Do not test simultaneous address loss by trusting auto-reset.
8. Record staging evidence and owner acceptance before production. Prepare/enroll production
   separately with its own identities/backups; proceed one server at a time and verify all
   voters and workloads between steps. Keep K-339 open until real-world behavior is accepted.
