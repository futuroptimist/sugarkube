# Ethernet DHCP recovery with data and quorum guards

K-339 remains open until owner-run staging and production qualification. This implementation
provides automatic local address refresh and an **optional, disabled-by-default recovery
controller** for one changed server while both other voters remain healthy. It does not
recover total quorum loss automatically. Static IP assignments, DHCP reservations and Wi-Fi
failover are not solutions used by these tools.

No live staging or production access was used to develop this change. Disposable local etcd
protocol tests use synthetic certificates and databases; they do not qualify K3s startup,
Node status convergence, application availability or the deployed clusters.

## Why mDNS and hostname peer URLs alone are insufficient

The K3s sources for both deployed versions define `NodeIPFlag` and `FlannelIfaceFlag` without
`EnvVars`. `K3S_NODE_IP` and `K3S_FLANNEL_IFACE` therefore do not configure those flags:

- [v1.35.4+k3s1 agent flags](https://github.com/k3s-io/k3s/blob/v1.35.4%2Bk3s1/pkg/cli/cmds/agent.go)
- [v1.34.5+k3s1 agent flags](https://github.com/k3s-io/k3s/blob/v1.34.5%2Bk3s1/pkg/cli/cmds/agent.go)

Use supported YAML `node-ip` and `flannel-iface`. A conflicting CLI option can override YAML;
configuration precedence must be verified before enrollment.

[K3s embedded etcd](https://github.com/k3s-io/k3s/blob/v1.35.4%2Bk3s1/pkg/etcd/etcd.go)
constructs its expected peer URL from `PrivateIP` and checks both member name and peer URL.
Changing persisted peer URLs to hostnames does not satisfy that check. The controller keeps
IP-based peer URLs and updates only the existing enrolled member's URL. mDNS locates the
survivors; authenticated cluster/member IDs establish their identities.

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

The pre-start command runs after `network-online.target`, has a 30-second timeout, and blocks
K3s execution if the address is missing, invalid or ambiguous, or the managed YAML is missing
or replaced. A failed refresh preserves the old file but does not allow K3s to consume it
through this start path. It writes only owned network YAML; it cannot migrate legacy files,
rewrite TLS policy or mutate membership. The installed copy does not depend on the checkout.

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

The controller uses etcd's
[JSON gateway](https://etcd.io/docs/v3.6/dev-guide/api_grpc_gateway/), which must be enabled.
It pins each discovered IP to an Ethernet-bound TLS connection, verifies the enrolled DNS
identity and CA, and checks cluster/member IDs in every response. Connections do not silently
reconnect between proof and mutation. Quorum proof uses a linearizable read from each survivor;
a TCP connection, mDNS answer, cached membership or API readiness is insufficient.

### Enrollment while healthy

Enrollment is an explicit owner operation after verified backups and a recovery drill. It
requires all three voters healthy, current peer URLs, matching Node UIDs/member annotations,
and converged Node addresses. It records the machine identity, original address, exact K3s
version, effective systemd settings, YAML files, environment files and trust-root hashes. Native etcd/API client certificate
renewal is allowed at the same protected paths; CA and configuration changes invalidate
enrollment. Only a standard inline-certificate kubeconfig is accepted, with no exec plugins
or token/file credential overrides.
The original address is a baseline for detecting changes, not a static assignment.

`python3-yaml` is installed by `scripts/install_deps.sh`. Standard K3s `kubectl`, Avahi,
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

### Address-change state machine

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

### Stale Node status and explicit resumption

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

## Total quorum loss

The controller cannot commit a peer-URL change without quorum and cannot choose the authoritative
database. Preserve every server database, token and configuration. Make and verify cold backups.
An operator must choose the seed and authorize any single-seed membership reset from existing
data; preserve peer DB directories and rejoin sequentially only after seed health and membership
are verified. No reset/deletion commands are generated by these tools. See
[etcd runtime reconfiguration](https://etcd.io/docs/v3.6/op-guide/runtime-configuration/).

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
