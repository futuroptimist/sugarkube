---
personas:
  - software
---

# Axel database platform design (K269 / P6)

## Status and privacy invariants

**Proposal only. No database, migration, deployment, cluster probe, credential change, or
runtime security test is implemented or performed by this document.** The companion Axel
design owns the application contract; this document owns the proposed Sugarkube boundary.
One K269 tracking card covers both separate design PRs and completes only after both are
owner-merged. A ready PR or green documentation CI does not complete that card or authorize
implementation. Companion PR linkage remains a coordination gate before implementation.

The following requirements are release blockers:

1. Authentication is not tenant authorization. Every server-side read, mutation, search,
   subscription, export, attachment access, and background job checks current membership and
   its allowed action. Client-supplied tenant or object identifiers never establish authority.
2. No private board data, snapshots, account identifiers, secrets, or production payloads enter
   public documentation, test fixtures, PR evidence, metrics, or model prompts by default.
   Use synthetic tenants and records. Staging never receives production credentials or data.
3. Untrusted card text, Slack messages, imported history, retrieved documents, and model output
   are data. None can grant tools, tenant membership, approval, or operational authority.
4. Current and archived cards must eventually migrate with stable IDs and history preserved.
   Cutover requires encrypted backups, a rehearsed restore, reconciliation, and owner approval.
   Imported historical approvals remain inert provenance and never authorize fresh actions.
5. Browsers and Sites use Axel's authenticated HTTPS API. They never connect to raw database
   TCP, receive database credentials, or hold a service credential that bypasses membership.
6. Production and staging have separate identities, secrets, volumes, backup prefixes and keys,
   release evidence, Slack installations, and login callback allowlists. Fail closed on mismatch.

## Evidence and existing boundaries

Repository inspection used main `bbf22182d8582794ea1fb221611fd8a23fb647f8` on 2026-10-10.
Root `AGENTS.md` applies; no nested `AGENTS.md` or `.agents/skills` files were present in that
checkout. This is source inspection, not a live cluster inventory. The supplied operational
baseline is one production three-node HA k3s cluster; a second production cluster is planned
and does not exist yet. HA control planes do not establish database HA or site redundancy.
Current Kepler is owner-private and single-board, not an existing multi-tenant service.
Do not infer that an application database layer already exists from Kubernetes' own datastore.

The [deployment contract](../app_deployment_contract.md) gives application repositories image,
chart, and release ownership, and Sugarkube environment selection and orchestration ownership.
The [platform design](app-agnostic-platform.md) documents remaining app-specific gates; Axel
must not silently inherit DSPACE-only release behavior. The
[staging ingress record](../staging-ingress-ha.md) proves limited DNS/ingress behavior, not
database durability. The [older rollout plan](../cluster-rollout-and-migrations.md) includes
aspirational Flux/storage choices; it is not proof those components are active.

| Responsibility | Accountable owner and interface |
| --- | --- |
| Identity, membership, tenant schema, application transactions | Axel; versioned HTTPS contract and explicit authorization model |
| GitHub login and later identity adapters | Axel; GitHub first, ChatGPT adapter only after eligibility and supported flow are verified |
| Slack signatures, deduplication, agent tools, approvals | Axel; durable inbox/outbox and narrow action capabilities |
| Schema migrations, compatibility and repair | Axel publishes immutable migration artifacts; Sugarkube runs a reviewed, environment-bound job |
| Database installation, patching, topology, storage | Sugarkube; selected engine/operator versions and verified ARM64 images |
| Backup infrastructure, encryption and restore orchestration | Sugarkube; Axel supplies semantic reconciliation and tenant-isolation assertions |
| Telemetry | Axel supplies safe application metrics; Sugarkube owns discovery, dashboards and alert routing |
| Promotion and disaster declaration | Human owner; reviewed evidence, explicit environment and single-writer recovery decision |

Axel's interface should include readiness and schema-compatibility status without tenant content,
bounded metrics, idempotency keys scoped to tenant/action, transaction retry semantics, and a
machine-readable release manifest. Credential values travel through secret references only.
Neither a generic HTTP proxy nor a caller-selected SQL query is an acceptable tenant data API.

## Engine evaluation and decision gate

**Provisional recommendation: evaluate PostgreSQL first as the operational and row-level security
(RLS) baseline, while keeping engine selection open.** This is a tradeoff judgment, not a claim
that PostgreSQL is memory-safe. Its implementation is principally C. Patch response, extension
minimization, process isolation and constrained access remain necessary. Language choice alone
cannot compensate for incorrect tenant policy, unrecoverable storage, or an unsupported HA setup.

| Candidate | Memory safety boundary | Durability, tenant controls and operational tradeoff |
| --- | --- | --- |
| PostgreSQL | C engine and native extensions are not memory-safe; a Rust client does not change this | Mature transactions, RLS, WAL recovery and replication form the baseline. HA orchestration and fencing still need an operator or equivalent reviewed controller. Small-footprint trials are plausible, not measured here. |
| CockroachDB with Pebble | Primarily Go, including Pebble storage; Go `unsafe`, runtime, native libraries and any `cgo` boundary still require exact-build review. Pebble contains explicit unsafe allocation code | Distributed SQL and consensus offer a credible HA alternative. PostgreSQL protocol compatibility is not identical SQL/RLS behavior. Prove tenant policies, retries, backup/restore, licensing and upgrade support for the pinned release. More capacity and distributed-system expertise are required. |
| SurrealDB with SurrealKV | Rust service and Rust embedded storage are credible memory-safety candidates, not an end-to-end guarantee; inspect `unsafe`, transitive crates, allocators and FFI in the chosen build | Different query/permission model requires Axel adaptation and equivalent authorization tests. Do not equate an embedded ACID store with supported multi-node HA or PITR. Current self-hosted Kubernetes documentation describes single-node RocksDB and separate Enterprise HA options. Validate exact supported backend, edition, recovery and ARM64 topology before selection. |
| SurrealDB with RocksDB or TiKV-based historical examples | Rust application code can still use native C++ RocksDB through FFI; a Rust label does not cover the storage stack | Additional services and consensus layers increase recovery and upgrade complexity. Historical deployment examples are not evidence of present supported HA. Do not adopt from an old tutorial without vendor-version verification. |

Official references reviewed on 2026-10-10: [PostgreSQL source](https://github.com/postgres/postgres),
[Pebble storage](https://www.cockroachlabs.com/docs/v25.4/architecture/storage-layer),
[Pebble unsafe allocation](https://github.com/cockroachdb/pebble/blob/master/internal/rawalloc/rawalloc.go),
[SurrealKV source](https://github.com/surrealdb/surrealkv), and
[SurrealDB Kubernetes topology](https://surrealdb.com/docs/manage/self-hosted/kubernetes).
These moving documentation/source links inform evaluation; implementation must pin release,
source revision, dependency lockfiles, image digest, edition and support policy in its evidence.

For each shortlisted build, inventory native/unsafe dependencies and extensions, verify published
`linux/arm64` artifacts and required CPU instructions on the actual Pi generation, and exercise
power-loss recovery, upgrade, failed migration, restore and tenant isolation. Compare observed
RSS, CPU, disk latency, write amplification, archive growth, operator effort and recovery time.
Do not call an engine memory-safe because its top-level repository is Rust or Go. OS, TLS,
compression, allocator, drivers and container dependencies remain part of the attack surface.

CockroachDB's [production guidance](https://www.cockroachlabs.com/docs/stable/recommended-production-settings)
recommends at least 8 vCPUs per node and strongly discourages fewer than 4; it recommends 4 GiB
RAM per vCPU. That is a material fit concern for shared Pi nodes. Do not reuse PostgreSQL's trial
budget below for a distributed SQL deployment. Engine approval requires documented capacity,
support/licensing, recovery evidence and owner acceptance of the residual memory-safety risk.

## Placement, storage and initial budgets

Use the separate staging cluster with entirely synthetic data. Proposed namespaces separate
Axel API and database responsibilities, but namespaces alone are not a security boundary.
No production restore enters ordinary staging. Any future production-data recovery exercise
needs an isolated production-security recovery environment and separate authorization.

Start evaluation with one staging database instance, then rehearse the proposed production
three-instance topology on distinct staging nodes. Proposed production PostgreSQL placement is
one primary and two replicas, each with its own persistent volume and required node anti-affinity.
No shared writable data directory. A disruption budget protects voluntary maintenance only;
it does not prevent node loss. A three-node cluster has no fourth placement slot: maintenance
may leave a replica pending and must never relax isolation silently.

Prefer dedicated SSD/NVMe volumes with tested flush/durability behavior, capacity headroom,
wear monitoring and stable node affinity. The [k3s local storage provisioner](https://docs.k3s.io/storage/)
provides node-local persistence, not database replication. Losing that node requires database
failover/rebuild, not assuming its local PV can attach elsewhere. Use retain-on-delete semantics,
explicit volume ownership and a separate reviewed reclamation procedure. Storage-class selection
and encryption-at-rest support remain open. No claim that Longhorn or another replicated storage
layer is installed; adding one requires its own resource and failure analysis. Avoid two opaque
replication layers unless measurements justify their combined latency and recovery behavior.

The following are proposed PostgreSQL experiment ceilings, not production sizing or guarantees:

| Component | Starting request / limit | Constraint to validate |
| --- | --- | --- |
| Each database instance | 500m CPU / 2 CPU; 1 GiB / 2 GiB memory | Three instances total 1.5 CPU and 3 GiB requested, up to 6 CPU and 6 GiB limited; tune memory for connections, sort work, maintenance and buffers |
| API instance, two proposed for production | 100m / 500m CPU; 128 MiB / 512 MiB | Bound total connection pools to 20 initially; do not multiply pool size unnoticed when scaling |
| Backup or migration job, one at a time | 250m / 1 CPU; 256 MiB / 1 GiB | Throttle I/O; schedule away from maintenance and do not overlap bulk import |
| Database PV per instance | 20 GiB starting allocation | Keep at least 30% free; separately budget WAL, indexes, temporary space and full replica rebuild |

Sugarkube must later inventory allocatable resources and existing reservations, reserve capacity
for k3s, monitoring and ingress, and prove service under one-node loss plus replica rebuild.
No live inventory was performed for this design. Reject scheduling if the safe budget cannot fit;
do not evict platform services or claim aggregate free memory is sufficient per node. Synthetic
tests should cover projected card/history volume and 10x bursts, imports, slow disks and backups.
Set statement, transaction, connection, queue and request size limits; avoid OOM restart loops.

## Availability and failure domains

Database replication is independent of k3s control-plane HA. Select and pin an operator only after
ARM64, k3s-version, fencing and recovery qualification. Replication credentials cannot modify
application data through the API. TLS authenticates replicas and rejects unknown peers.

For PostgreSQL, evaluate synchronous acknowledgement by at least one replica for production
durability. If no qualified synchronous replica remains, stop writes rather than silently degrade
the guarantee. Async replicas may lag; promotion must evaluate replay position and loss bounds.
Only a fenced primary can write. A partition, stale lease or ambiguous fencing stops promotion;
the returning former primary is rebuilt or safely rewound before rejoining, never made writable
on the strength of an old lease. Test the operator's actual semantics, not only its replica count.
See [PostgreSQL standby behavior](https://www.postgresql.org/docs/18/warm-standby.html).

Three nodes in one site still share power, network, physical access and possibly storage failure
domains. Neither replication nor a PV snapshot protects against application deletion, corruption,
operator compromise, theft or site loss. The future second cluster should initially be a cold or
warm recovery target with independent storage, keys and failure domains; it is not current capacity.
Do not stretch consensus across two sites and assume either can independently remain writable.
Cross-cluster active/active operation and conflict resolution are explicitly deferred.

## Network, identity and secrets

Only the API receives public HTTPS through the reviewed ingress/tunnel path. A proposed staging
host such as `axel-staging.example.invalid` is a placeholder, not an allocated DNS record.
Select real staging/production hosts, owner and certificate issuer in a later implementation PR.
Use distinct exact OAuth callbacks and host-only secure cookies. Verify TLS from browser to edge,
edge to origin and API to database, including hostname/CA validation and rotation. No plaintext
origin exception or public database Service is allowed. Trust proxy headers only from known ingress.

Default-deny network policies must allow only API-to-DB, replica-to-replica, controlled migration
jobs, approved monitoring, DNS and backup destinations as necessary. Confirm the active network
plugin actually enforces ingress and egress policies. Namespace labels alone are not a trusted
identity if an attacker can label pods; admission/RBAC must prevent impersonation. Restrict API
egress to required identity/Slack services and explicit approved agent tools. Block metadata,
cluster administration and arbitrary internal destinations; defend against SSRF and DNS rebinding.

Use separate runtime, migration/owner, replication, monitoring and backup roles. Runtime cannot
create schema, assume owner roles, manage grants, install extensions or read backup keys. For
PostgreSQL it must not own tables, be superuser or have `BYPASSRLS`; require `ENABLE` plus
`FORCE ROW LEVEL SECURITY` on tenant tables. `FORCE` does not constrain superusers or
`BYPASSRLS`. Review views, functions, grants, `search_path`, inheritance and bulk operations.
Use both row visibility and write checks, tenant-bearing foreign keys, and generic errors for
constraint conflicts. RLS does not cover `TRUNCATE` or prevent privileged compromise; deny
runtime those capabilities. See [PostgreSQL RLS semantics](https://www.postgresql.org/docs/18/ddl-rowsecurity.html).

Tenant context is set only by the trusted server after membership validation, transaction-local
and cleared before connection reuse; missing context denies access. A setting that the runtime
can change is defense in depth against missing filters, not protection from a fully compromised
API. Prevent SQL injection with parameterized queries and no arbitrary query endpoint.

Use short-lived or rotated workload credentials where supported, separate environment secret
references, encrypted secret storage and tightly scoped service accounts. Do not mount migration,
backup or cluster-admin credentials in the API or agent. Keep database auth, Slack signing keys,
OAuth secrets and backup decryption keys out of Git, URLs, Helm history and logs. Rotation and
key recovery are acceptance tests; encryption without recoverable keys is not a recovery plan.

## Backups, restore and disaster recovery

Proposed owner-review targets: RPO <= 15 minutes for off-cluster recovery and RTO <= 4 hours
from incident declaration to verified service. A fenced synchronous failover targets no lost
acknowledged transactions and service within 5 minutes, subject to rehearsal. These are objectives,
not achieved SLOs; common-site failure depends on off-site backups and available replacement compute.

Propose daily base backups plus continuous WAL archiving, 35 days of recovery retention, and
independent encrypted off-site copies. Confirm retention, data deletion obligations and costs
with the owner. Use engine-consistent backups, authenticated transport, integrity manifests and
client-side encryption with separately held recovery keys. Archive writers must not delete older
backups; retention administration has a separate identity. Evaluate immutable retention against
privacy deletion requirements. PV snapshots alone are not sufficient; use supported consistency
coordination. PostgreSQL PITR depends on a valid base backup and an unbroken WAL sequence:
[official recovery guidance](https://www.postgresql.org/docs/18/continuous-archiving.html).

Rehearse monthly with synthetic data and after engine/operator/schema changes. Measure last
recoverable transaction and full elapsed recovery time, including obtaining keys, provisioning,
replaying, verifying membership/RLS, validating IDs/history and opening HTTPS traffic. Corrupt a
copy, remove WAL, deny keys and simulate unavailable backup storage; each must fail visibly.
Evidence contains checksums, versions, timings and counts only, not recovered content.

Recovery order: declare incident; fence all old writers and pause Slack/agent consumers; select
verified backup and release/schema pair; restore isolated volumes; validate integrity, tenant
access and history; rotate exposed credentials if needed; invalidate old sessions and pending
capabilities; reconcile durable inbox/outbox deduplication; approve the new writer; switch DNS/
ingress with bounded cache assumptions; verify; resume bounded consumers. Never replay side
effects merely because a restored outbox says pending. Use external action reconciliation and
fresh approval where outcome is uncertain. Keep the old cluster fenced during failback and
reseed it from the authoritative lineage rather than merging divergent histories.

## Schema, release integrity and legacy migration

Axel publishes reviewed migration checksums and required/current schema ranges with immutable
code revision, image and chart digests. Sugarkube's proposed release evidence additionally binds
environment, values digest, engine/operator versions, schema target, migration set and staging
test results. Tags alone are mutable references: resolve and record immutable identities and
refuse mismatches. A successful tag workflow does not establish a supported Sites publication
credential. External tagged release-to-Sites automation is unverified; keep an explicit manual
publication/verification gate until a supported mechanism is established.

No migrations on API startup. A single serialized, bounded migration job obtains a database lock,
checks starting schema and backup freshness, uses temporary migration authority and records its
result. Prefer expand/backfill/verify/contract across releases, bounded batches and dual-version
compatibility. Tenant columns/policies exist before any newly accessible data. A failed migration
blocks promotion; operators inspect recorded progress and use a reviewed idempotent forward
repair. App rollback is allowed only within the declared schema compatibility range. Destructive
schema rollback is not a Helm rollback: restore into isolation or repair forward with explicit
data-loss analysis and owner decision. Do not automatically restore over newer valid writes.

Legacy migration is a separately authorized project: inventory current and archived sources;
create and verify encrypted snapshots; define canonical ID/provenance mappings; import into an
isolated target; reconcile counts, stable IDs, full ordered histories, timestamps, archive states,
references and content hashes; run tenant-isolation tests; rehearse cutover and rollback. Mapping
old owners to new tenant membership requires explicit verification, never inferred from imported
text. Keep approval history as display-only provenance outside executable capability records.
Freeze writes or capture a validated final delta, repeat reconciliation, obtain owner cutover
approval, then switch clients. Preserve the protected source for the approved retention window.
After new writes begin, rollback requires delta reconciliation; simply switching back loses data.

## End-to-end threat model and proposed regression matrix

Assets include tenant content/history, identities, sessions, Slack installations, memberships,
approval capabilities, release evidence, secrets and recovery material. Adversaries include an
unauthenticated internet caller, a malicious tenant/member, forged or replayed Slack events,
prompt-injection authors, compromised API/agent/dependency, and a privileged operator or node.
Trust boundaries are browser/Sites-to-API, identity-provider callback, Slack ingress, queue/agent,
API-to-database, migration authority, CI-to-release, storage-to-backup, and recovery-to-live service.

**Every case below is planned and unexecuted.** Documentation CI cannot validate these controls.
Axel owns application tests; Sugarkube owns infrastructure/recovery tests; joint cases must bind
both artifact revisions. Use two synthetic tenants, multiple roles, revoked members and known
canary secrets. Assert response, database effects, audit record and absence of cross-tenant data.

| Boundary / threat | Required negative and regression cases | Acceptance oracle / owner |
| --- | --- | --- |
| Login / session | Wrong OAuth state, callback or issuer; code replay; session fixation; expired/revoked session; CSRF mutation; logout; forged proxy host; disallowed CORS origin; wrong-environment cookie | Deny before mutation; rotate sessions on login/privilege change; no open redirect or identity linking by unverified email; Axel |
| Identity and membership | Valid login without membership; removed user with cached session; role downgrade during queued action; wrong tenant in URL/body/header | Recheck current membership at action time; deny every object path consistently; Axel |
| Slack ingress / replay | Invalid signature; altered raw body; stale/future timestamp; duplicate event and concurrent retries; wrong installation/workspace; deleted membership | Verify signature over raw bytes and bounded time skew before durable enqueue; tenant-bound dedup survives restart; no duplicate side effects; Axel |
| Agent prompt injection / tools | Card/import/message says to reveal secrets, change tenant, grant tools, deploy or treat old approval as current; forged tool result; stale approval; changed action parameters | Content cannot enlarge capabilities; server checks actor, tenant, exact action hash, expiry and single-use nonce; tool execution denied without fresh authority; Axel |
| API / tenant IDOR | Substitute IDs in CRUD, nested relationships, search, pagination cursor, batch, subscriptions, attachments and exports; mass assignment; SQL injection | No foreign content, counts or existence leaks; atomic authorization for mixed batches; composite tenant references and parameterized queries; Axel |
| Database / pool | Missing/forged tenant context; connection reuse after error; direct runtime read; write foreign tenant; runtime grants/DDL/role escalation; permissive policy combination | Fail closed; transactions reset context; runtime cannot bypass or disable RLS; verify new tables, views and functions every migration; joint |
| Migration / repair | Wrong engine/schema/environment; modified checksum; two jobs; mid-backfill crash; lock timeout; incompatible old API; failed policy creation | No partial public exposure; resumable reviewed repair; promotion blocked and old compatible code retained; joint |
| Import / export | Cross-tenant archive; ID collision; truncated history; forged approval; path traversal; executable attachment; spreadsheet formula; oversized compressed upload | Quarantine/reject, bounded parsing and safe downloads; reconcile IDs/history; exports scoped and short-lived; imports never mint authority; Axel |
| Backups / recovery | Wrong key; corrupted base; missing WAL; stale backup; production restore into staging; compromised archive writer; old primary returns; pending external action after restore | No silent success, no unauthorized restore or split writer; measured RPO/RTO and semantic checks; joint |
| Secrets / logs | Canary in auth headers, query strings, SQL errors, Slack payload, tracing, metrics, crash report and model/tool context | No canary in logs, public evidence or model input; bounded retention and access; safe audit metadata only; joint |
| Supply chain / release | Reassigned tag; digest mismatch; untrusted migration image; wrong ARM64 build; altered dependency; stale CI result; PR code requesting deployment secret | Reject release; pin artifacts, verify provenance and scan dependencies; untrusted CI gets no production credentials; joint |
| DoS / resource exhaustion | Connection flood; hot tenant; expensive query; queue growth; import bomb; log-cardinality burst; archive outage filling WAL; disk full; node pressure | Per-tenant quotas, deadlines and backpressure; bounded queues; platform survives; alerts before exhaustion; joint |
| Network / TLS | Untrusted pod reaches DB; label spoof; staging reaches production; expired/wrong-host cert; SSRF to metadata/admin; DNS rebinding | Enforced default deny and identity controls; no insecure retry; only reviewed traffic paths; Sugarkube |
| Failure / recovery | Primary loss; partition; one-node maintenance; disk corruption; total site loss; backup endpoint unavailable; lost recovery key | Single writer or explicit unavailable state; validated recovery timing/data bounds; no assumed second cluster; Sugarkube |

Slack implementation should follow [official request verification](https://docs.slack.dev/authentication/verifying-requests-from-slack/).
Deduplication is additional to signature verification; a valid signature alone is neither current
tenant authorization nor approval to execute an agent action.

## Observability, gates and residual risks

Follow the [observability design](../observability-design.md) and
[alert strategy](../observability-alerting.md). Monitor readiness separately from write availability,
replication lag, archive continuity/age, restore rehearsal age, volume free space and growth,
I/O latency, restarts/OOM, connection saturation, transaction latency/deadlocks, failed migrations,
denied authorization, Slack dedup/queue age and TLS expiry. Avoid tenant/card IDs and content as
metric labels. Restricted audit records contain actor reference, action, environment, outcome
and correlation reference, never content or credentials; retention and access remain owner decisions.

Proposed alerts: page on no safe writer, fencing ambiguity, archive age over 15 minutes or imminent
disk exhaustion; warn at 30% free disk, 80% connection utilization, missing daily backup or overdue
monthly restore. Validate thresholds against measured growth and acceptable noise. A separate
off-cluster heartbeat is needed to notice total cluster loss. Alert tests must verify routing,
deduplication and recovery notification with synthetic events before enabling production.

Implementation may begin only after both design PRs are owner-merged and a separate scope is
approved. Then require engine/operator/storage selection, measured spare capacity, supported
ARM64 artifacts, agreed RPO/RTO and retention, exact API/release interfaces, DNS/TLS ownership,
all negative tests implemented with recorded outcomes, and a restored synthetic staging rehearsal.
Production import requires its own protected backup and reconciliation/cutover approval.

Residual risks: a compromised trusted API or privileged operator can defeat tenant controls;
RLS is defense in depth, not a sandbox for arbitrary SQL. Memory-unsafe dependencies remain even
with safer-language candidates. Shared power/network limits site availability. Key loss can defeat
recovery. Backups can preserve deleted sensitive data until retention expires. Timing/constraint
side channels, noisy neighbors, ambiguous external side effects and human recovery errors remain.
ChatGPT sign-in eligibility, Sites publication automation, second-cluster independence, exact
capacity and recovery performance are unresolved. No risk here is declared mitigated by prose.
