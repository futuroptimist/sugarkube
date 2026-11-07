# Guarded existing-enrollment migration

This is **source implementation with offline tests**, not live qualification or
permission to operate a cluster. No lab or cluster operations were performed while
implementing it. Operational execution requires a separately approved one-server
window, current private evidence and verified backups. Never run fake backends
against a real server.

The [historical read-only planner](ethernet-migration-planner.md) and its catalog
remain unchanged. `ethernet_migration_apply.guarded_plan(bundle)` evaluates the same
source admission rules against a separate immutable guarded target catalog,
`resolver-v1-to-guarded-directory-v1.json`. A plan still says
`authorized_to_execute: false`. A plan is not operational authorization.

## Source interface and deployment boundary

`scripts/ethernet_migration_host.py` supplies the concrete host adapter. Its `plan` action requires a baseline and writes a guarded plan to an explicit
private output. `capture` requires baseline, plan, receipt and private output.
`apply` requires baseline, plan, receipt and the pinned runtime directory. It does not pause remote timers, obtain permission, create backups,
restore databases or install its own operational tools. Capture writes an exclusive private output file. It contains configuration
metadata and must be handled as private operator evidence, never posted to public
logs.

The guarded controller target is an immutable source commit recorded in the new
catalog. A runtime directory must contain every exact pinned runtime file under
its installed filename, including `ethernet-quorum-recover.py`. Unpinned or current
working-tree bytes that differ from the catalog refuse. The adapter, planner,
apply module and catalog must themselves come from a reviewed trusted source;
this implementation is not a self-updater or deployment mechanism.

Do not substitute the historical `b320c583` controller. That controller does not
recognize migration intent and cannot safely fence migration activation.

## Private operational receipt

The receipt must be root-owned with mode `0600`. JSON and runtime reads are bounded
to 128 MiB each. Backup verification instead streams in 1 MiB chunks, with a 1 TiB
size ceiling and a 120-second per-file deadline. It verifies the trusted open file
and pathname still have the same device, inode, size and timestamps after hashing;
truncation, growth or replacement refuses. The shorter admission freshness window
still applies before mutation.

The receipt is a trusted private operator input, not proof that the assistant
performed or observed an operational action. The host adapter validates its exact
schema and checks:

- Canonical hashes of the specific guarded plan and original baseline.
- Issue and expiry times with a maximum five-minute window, plus a shorter
  monotonic deadline around fresh admission.
- Explicit one-server window, backup, timer, controller and lock gates.
- Per-original-member attestations that timers are paused, controllers idle and
  local membership and Node-address intent absent.
- The baseline backup commitments and local snapshot, original bundle and restore
  evidence file paths. It hashes actual trusted local bytes against those
  commitments. A matching restore-evidence digest does not prove a restore worked;
  restore verification remains the approving operator's attestation.
- An existing pod DNS probe, bound to namespace, pod UID, local Node placement,
  container, hostname and expected address. No probe workload is created.

Remote local journals and timer state cannot be proven by healthy Nodes or an
absent etcd key. These remain explicit operator attestations. Independently, the
adapter rechecks observable local metadata and identity, authenticated original
etcd endpoint status and linearizable health, exact membership, Node identity,
readiness and addresses, enrollment markers and lock state. It never presents
remote attestations as newly authenticated remote filesystem evidence.

The receipt is not a cryptographic identity mechanism: trusted ownership and
separate operational approval are required. The enrollment's old
`verified_backup` boolean alone is insufficient.

## Mutation ordering and preservation

The orchestrator regenerates the entire expected plan, verifies exact equality
with the approved plan, verifies all runtime hashes and renders only pinned
templates and the planned DNS configuration. It admits a fresh challenge-bound
capture and rejects changed facts instead of silently replanning.

Under the local recovery lock, it creates and syncs a single-use intent before
cluster lock acquisition or host changes. A random operation identity and exact
plan hash bind the cluster owner; the plan hash alone is not an owner. Individual
phase records are synced before acquisition, stopping, each replacement,
activation, release and timer resume.

After compare-and-set acquisition of the existing recovery membership key, the
adapter rechecks evidence under its exact ownership. It stops only local K3s and
its resolver and proves no relevant consumer or old controller remains. The
**guarded controller is the first replacement**, before resolver configuration or
enrollment changes. Every replacement checks the expected old bytes, preserves
metadata and saves the original file for inspection, then syncs and verifies the
new file. Enrollment is written last.

Member, Node, machine and database identities, trust inventory, original recovery
journal and unrelated enrollment fields remain unchanged. The standard dynamic
network YAML has a separate startup boundary described below. There is no reset,
member add/remove, Node patch, credential change or database restore in this path.

Before activation, the adapter saves the exact bytes and metadata of the managed
`20-sugarkube-network.yaml` file. The existing network refresh hook runs before the
migration guard during service startup and may rewrite this dynamic YAML if DHCP
changes in that interval. The migration guard then refuses the changed baseline
before normal recovery or K3s starts. This is an explicit startup side-effect
boundary, not a promise of zero file writes on failure. The saved original bytes
and intent remain for operator review, with no automatic rollback. Successful
completion checks the expected baseline network YAML again.

The old controller cannot understand the new intent before it is replaced. The
paused controllers, local lock, stopped services and explicit no-consumer proof
therefore remain essential at that first replacement boundary.

## One-start guard

The adapter installs `migration-start-permit.json` before releasing the local lock
for service startup. The guarded controller checks migration intent before normal
controller actions. During migration it refuses watch, resume and other recovery
actions. A pre-start permit binds the exact owner, installed target enrollment,
original incident and baseline Ethernet address. The guard independently checks
configuration, database identity, network, absent Node-address intent and current
cluster lock ownership.

The guard also verifies the real systemd invocation ID, startup substate and
control group, plus the process's own unified control-group membership. The
supported layout is `/system.slice/k3s.service`; other layouts fail closed. An
environment variable alone is insufficient.

It durably creates an exclusive consumed-permit file before allowing one baseline
start. Post-start must belong to that same systemd invocation. Neither path calls
normal recovery logic or changes the original incident. An unknown startup result
cannot reuse the permit.

Lifecycle jobs use a separate allowlisted runner, not the 12-second read-only
probe deadline. Caller limits are 420 seconds for K3s start, 180 for K3s stop,
45/30 for resolver start/stop, and 30 for reload or timer start, within a
600-second cumulative lifecycle budget. Existing systemd unit timeout settings
are unchanged. Each operation is recorded before dispatch; definitive failure,
unknown dispatch or timeout never triggers another submission. A timeout may
leave a systemd job running and requires reconciliation.

The adapter reacquires the local lock after activation. Completion allows normal
Node, pod and workload readiness to converge under a 120-second polling budget
and at most 61 read-only attempts, with bounded delays. No new attempt starts
after that budget. Time spent reading counts toward the budget, and an overdue
proof cannot report completion. An already-running read remains subject to its
own bounded probe timeout before control returns. Every attempt rechecks immutable facts,
exact ownership and the consumed startup permit. Only specifically classified
readiness conditions are pending; identity, artifact, trust or unknown failures
refuse immediately. Activation and other mutations are never retried.

Before releasing its cluster lock it verifies exact files and enrollment, preserved identities and
journals, authenticated original quorum and Nodes, loaded units and real resolver
process views, existing-pod DNS and workload HTTPS. It releases only its exact
owner with compare-and-set, records completion and then resumes the local timer.
Final checks run again. Remote timers are not resumed by this one-server operation.

The completion record allows ordinary recovery again only for the exact migrated
enrollment. Future DHCP changes and recovery journals are intentionally allowed
through normal recovery checks after completion; the original baseline address
is not a permanent post-migration requirement.

## Failure and reconciliation

A missing, changed or ambiguous fact refuses. Any failure after durable intent may
mean the previous operation already happened. There is no automatic retry,
rollback, deletion, resume or reconstruction of an uncertain operation. Existing
intent, even truncated or apparently complete, prevents another apply attempt.
A cluster-lock timeout must not be treated as an unexecuted compare-and-set.

Preserve original backups, replacement backups, intent, phase records and startup
permit/consumption evidence for explicit reconciliation. Do not clear these files
just to retry. A failure after timer resume may require operator attention; a
successful earlier phase is not an overall completion claim.

## Offline verification

```sh
python -m pytest -q tests/test_ethernet_migration_apply.py \
  tests/test_ethernet_migration_guard.py tests/test_ethernet_migration_host.py \
  tests/test_ethernet_migration_plan.py
```

Tests use temporary roots, fabricated pinned catalogs and fake backend boundaries.
They cover exact binding, receipt expiry, capture drift, guard-first and
enrollment-last ordering, durable intent, uncertain outcomes, replay refusal,
path safety and the one-start fence. Real service, cluster, mount, IPC and DNS
qualification remains a separately approved operational step.
