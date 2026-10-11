---
personas:
  - software
---

# Axel database platform design (K269 / P6)

## Status and privacy invariants

**Proposal only. No database, migration, deployment, cluster probe, credential change, or
runtime security test is implemented or performed by this document.** The companion Axel
design owns the application contract; this document owns the proposed Sugarkube boundary.
One K269 tracking card covers [Sugarkube #2910](https://github.com/futuroptimist/sugarkube/pull/2910)
and [Axel #251](https://github.com/futuroptimist/axel/pull/251), and completes only after both are
owner-merged. A ready PR or green documentation CI does not complete that card or authorize
implementation. Keep independent exact-head checks, reviews and owner merge receipts on the card.

**Privacy-mode amendment (proposed).** The initial proposed
mode explicitly trusts narrowly scoped server/integration endpoints and is not operator-blind
E2EE. Full E2EE is a separate optional long-term extension, not an initial implementation blocker.
Neither mode's proposed controls are claimed to exist in current code.

The following requirements are release blockers:

1. Authentication is not tenant authorization. Every server-side read, mutation, search,
   subscription, export, attachment access, and background job checks current membership and
   its allowed action, including private-board scope within a tenant. Client-supplied tenant,
   board or object identifiers never establish authority.
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
7. Initial trusted-server mode permits plaintext only in explicitly authorized processing paths.
   Require tenant/board authorization, least privilege, disclosure minimization, safe logging,
   revocation/audit and qualified encryption in transit and at rest. Privileged operators of
   running services or key-management systems may still access content; do not call this E2EE.
8. Optional future E2EE has a distinct client/key and integration contract. Never silently change
   a board's privacy mode or treat enabling a feature as permission to disclose decrypted content.

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
| Initial encryption/key management | Sugarkube storage, transport and backup keys; Axel limits application/integration plaintext paths |
| Optional future E2EE keys and client trust | Axel trusted clients; independently reviewed protocol, device/board key lifecycle and recovery |
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

The [Axel contract previously inspected](https://github.com/futuroptimist/axel/blob/4023352e779a9a46b05d75f64be3654f527b3eb5/docs/design/sanitized-kanban-contract.md)
defines `ReleaseManifest v1`, tenant/board-scoped API commands and a separate private local
profile. This Sugarkube proposal applies only to the explicitly enabled online service. Its
off-site backups do not relax the sensitive profile's device-local backup and exact outbound
packet approval rules. Online workers cannot mount the private corpus or access its inference
service, local UI or backups. Reuse the Axel bounded backup/transfer codec rather than inventing
a second card-export format; physical database recovery remains a separate operational layer.

That inspected revision predates this privacy-mode amendment; no unseen companion amendment or
final head has been reviewed here. The proposed paired contract is `K269 privacy modes v1`:
explicit initial trusted-server processing and a separately qualified optional E2EE extension.
Before publication, compare both local proposals; before
merge, record both actual reviewed heads and the agreed contract digest in a separate review
receipt. Do not embed each final document hash in the other or create a circular hash dependency.
An agreed contract version is not evidence that uninspected code or prose is compatible.

## Initial trusted-server mode (proposed)

Initial delivery may trust the API/server, explicitly authorized ChatGPT dot/agent and Slack
integration endpoints
with plaintext only where their enabled function needs it. This is the initial design choice,
not an assertion that current code implements its controls. It permits useful validation, search,
automation and Slack workflows without claiming protection from every hosting administrator.
The trust inventory must identify each processor, its operator/model provider where relevant,
tenant/board scope, data fields, destination audience, retention and purpose before enabling it.
Default-deny unrelated processing and cross-tenant access. An identity login does not grant access
to arbitrary tenants, and a service role is not authority to process every board.

Keep the runtime, migration, backup and integration privilege split. Use scoped short-lived
capabilities where supported, explicit feature enrollment, immediate policy rechecks at execution/
delivery, bounded retries and revocation paths for removed members, devices and integrations.
Record safe audit metadata for grants, use, denial and revocation; exclude raw content and secrets
from ordinary logs, traces, metrics, public errors, support bundles and CI evidence. A support
exception needs explicit minimum content, recipient, retention and purpose, not unrestricted DB
access. Minimize durable plaintext copies, caches, prompts and provider retention. Enforce the
existing private-local profile's separate restrictions; this mode does not authorize its data egress.

Require validated TLS on every transport leg and encryption at rest for database/PV media,
WAL, replicas, temporary spill files, attachments, snapshots, backups and sensitive queues/caches,
with qualified algorithms,
implementations and platform support. Decide and test key custody, least-privilege access,
rotation, revocation, recovery, audit and environment separation before production. Keys must not
be stored alongside ciphertext under the same unrestricted backup credentials. State exactly
which host, service and recovery roles can decrypt. Mounted disks, authorized runtime processes,
database administrators or key-management operators can still expose plaintext; TLS and storage
encryption do not provide operator blindness. Key loss and retained-copy risks remain.

Dots/agents get explicit tenant/board/action scope and minimum necessary context; disclose any
model provider receiving content and do not infer unrestricted tool authority from readable text.
For ChatGPT dots, selected plaintext enters OpenAI processing; do not promise local-only handling,
zero retention or guaranteed deletion. Verify the actual dot/MCP authentication, recipient/audience,
connectivity and revocation capabilities before enabling the adapter. Website sign-in eligibility
does not prove agent authorization or product entitlement. Unsupported capabilities fail closed,
never by using shared administrator credentials. Tenant-owner grants bind recipient, fields,
read/write tools, purpose, expiry and exact or clearly bounded standing disclosure scope, and
request identity/revision checks prevent replay or substitution. No blanket future-data grant.
Slack already receives posted messages and its authorized receiving endpoint sees message
content. Verify requests before processing, bound event retention, and recheck membership and
destination audience before replies. Generic content-free notifications are a lower-disclosure
option, not a claim that enabled ordinary Slack intake is E2EE. Generic replies link to the app
entry without card IDs or titles. Card-specific replies require Axel's durable audience/history
constraint covering future joiners, rejoiners and connected organizations; without that proof,
withhold the card-specific link. Minimize unfurls and mentions.
Revoke future access when enrollment ends; do not promise deletion of prior recipient copies.

Initial-mode acceptance remains proposed and unrun: exercise cross-tenant/board denials, revoked
members/integrations, excessive agent scopes, wrong reply audience, transport certificate failure,
unavailable/rotated storage keys, backup restore and canary leakage through logs/prompts/support.
Positive controls prove only explicitly enrolled processing succeeds. Inspect raw media/backups
for the claimed at-rest protection while acknowledging that authorized running endpoints decrypt.
Test the key-management and data-flow inventory, not just an encryption configuration flag.

Track the optional full E2EE extension in [Axel roadmap issue #252](https://github.com/futuroptimist/axel/issues/252).
Axel owns that single public issue; do not create a duplicate in Sugarkube. It covers future client
trust, collaboration, recovery, integration and migration qualification. Initial scoped ChatGPT
dots and Slack support does not require a local gateway: that is an optional future E2EE route.
This design grants no automatic credential access, feature enrollment or data-sharing authority.

## Optional future operator-blind E2EE mode (not implemented)

The following requirements apply only to opting into the future full E2EE mode. They are not
initial-mode acceptance blockers. Adoption requires separate design/implementation approval;
do not advertise the mode until all its end-to-end qualification gates pass. Card content,
full history and attachments would be encrypted/decrypted only at authorized independently
trusted endpoints; hosting/API/database/backup operators would receive ciphertext and declared
metadata, not content keys. GitHub login and operator credentials would not unlock content.

Bind confidentiality mode to authenticated board metadata, client policy and release compatibility;
an operator-supplied flag is insufficient. Downgrades, plaintext export, old clients, migration
and recovery must not silently switch modes. Require a separate authorized disclosure decision,
show the effective mode, and separate grants/caches across modes. Unavailable E2EE clients fail
closed rather than falling back to server decryption.

Disk encryption, TLS, database access control and operator-managed encrypted backups remain
necessary but do not hide plaintext from a privileged running server. PostgreSQL's
[encryption guidance](https://www.postgresql.org/docs/18/encryption-options.html) distinguishes
client encryption from server-side decryption, where data and keys are exposed to administrators.
Do not implement this requirement with `pgcrypto` decryption, a server key service, or a hosted
API that briefly decrypts and promises not to log the result.

### Keys, collaboration and trusted client delivery

GitHub authenticates an Axel principal and the server checks membership; it supplies no content
decryption secret. An authorized user separately unlocks their client key material locally with
their own password. Generate content, board-epoch and device/user keys with a cryptographic random
source; do not use a password directly as a board key. Derive a local wrapping key using a vetted
memory-hard KDF such as Argon2id, unique salt and versioned parameters, then authenticated-encrypt
the random private key material. An operator password must never unlock all tenants. Separate
this secret from any login credential; neither raw nor derived wrapping secret reaches hosting.

Use [RFC 9106](https://www.rfc-editor.org/rfc/rfc9106.html) for Argon2id qualification and test
vectors, with reviewed device-specific memory/time budgets, parameter floors and upper bounds.
The chosen KDF, authenticated encryption, signatures and recipient key encapsulation must come
from maintained, vetted libraries/protocols with pinned versions, independent security review,
known-answer tests and supported client/ARM64 builds. Algorithm names alone are not a protocol.
Do not invent group cryptography or treat Web Crypto primitives as a complete E2EE library.

Use an independent random key per board epoch, with separately generated object/attachment keys
wrapped for that epoch as the qualified protocol requires. Deliver board keys only to authorized
recipient devices through authenticated key envelopes. Verify recipient/device public keys against
an independently established fingerprint or an already verified device plus a qualified signed
membership/key-directory consistency mechanism. A server-supplied directory or GitHub identity
alone cannot prevent the operator substituting its own recipient key. Require independent
verification for first contact and recovery enrollment; block unexplained key changes rather than
automatically trusting them. Server membership changes alone cannot mint a valid client key grant.

Enroll new devices through a verified existing device or explicit user-held recovery procedure,
binding device, principal, board scope and key epoch. Show grants/revocations to members and retain
authenticated membership history. On member removal, device compromise or changed membership,
rotate to a fresh board epoch and redistribute only to currently verified recipients before new
writes. Define whether new members receive history; history access requires deliberate key grants.
Shared board encryption alone does not prove which member authored a revision: authenticate
writers and membership transitions using the reviewed protocol. A member who retained old keys,
plaintext, screenshots or exports can still read those copies; rotation cannot erase past access.

The trusted client/update boundary must be independent of the hosting operator. Prefer a verified,
pinned client with independently controlled signing/update approval and downgrade protection;
identify who controls that trust root and how users verify it. A website served by the same
operator can replace the next JavaScript version and steal an unlock password, keys or plaintext.
TLS, CSP, a digest hosted on that website, and non-exportable Web Crypto keys do not alone prevent
malicious same-origin code from using secrets. The
[Web Crypto security considerations](https://www.w3.org/TR/2017/REC-WebCryptoAPI-20170126/#security-considerations)
make execution-environment trust relevant. If Sites cannot meet independent client verification,
label it a weaker trusted-frontend profile, require explicit acceptance, and do not claim hostile
hosting-operator protection. Qualification must include the update channel, not just initial install.

### Ciphertext storage and visible metadata

Sugarkube must store only encrypted content payloads in primary tables, WAL, replicas, physical
and logical backups, snapshots, exports, object storage, queues, caches, crash dumps and support
bundles. Card titles, descriptions, comments, revisions, attachment names/previews and
content-derived indexes belong inside the encrypted boundary, as do private links/dependencies,
PR URLs and content-bearing action details/receipts unless separately approved for minimum
disclosure. Do not generate server-side thumbnails,
plaintext materialized views, embeddings or content logs. Operator access to a running database,
mounted disk or outer backup key may expose metadata and ciphertext, but must not expose content
keys. Instrumentation and synthetic diagnostics must not turn into a plaintext recovery channel.

The initial visible metadata inventory includes opaque tenant/board/object IDs, account and device
public identifiers, membership/routing relationships, public keys and encrypted key envelopes,
crypto/schema versions, key epochs, revision/operation numbers, timestamps, ciphertext sizes,
storage counts and access/network patterns. Encryption does not hide board existence, who works
together, update frequency or attachment size by default. Minimize this inventory; do not put
titles or semantic workflow labels in routing metadata. Padding, batching and stronger metadata
privacy are separate design choices with capacity costs. Do not publish deterministic plaintext
hashes of low-entropy content; keep semantic hashes inside encryption or use reviewed client-held
keyed commitments where needed. Public schema fields and approval metadata need explicit review.

Authenticate ciphertext and its context: tenant, board, object/attachment/chunk identity, content
type, format/crypto version, key epoch, revision and intended operation. Specify canonical encoding,
nonce uniqueness and domain separation in the qualified protocol. Detect substitution across
tenants, boards, versions and chunks, as well as truncation/reordering and unauthorized authors.
The server may enforce envelope shape, length quotas, access policy and opaque revision ordering;
trusted clients verify cryptographic integrity and semantic content before display or action.

Authenticated encryption detects changed bytes, not replay of an authentic older state. Clients
need independently retained checkpoints and a qualified consistency/freshness mechanism for board
epochs, membership, history and consumed authority. An operator can withhold writes, present split
views or replay a valid old backup. A new/reset device with no trusted checkpoint or independent
witness cannot prove it saw the latest state; disclose that limit and block sensitive activation
or dispatch until freshness is independently reestablished. Server-only counters and
operator-controlled backup manifests are not independent rollback protection. Ciphertext durability and
recovered cryptographic freshness must be reported separately.

### Plaintext-dependent features and key recovery

Search, content validation, attachment scanning, previews and semantic migrations run in trusted
clients or explicitly user-controlled endpoints. Server validation covers only opaque structure,
authorization and bounded resources; it cannot truthfully inspect encrypted card semantics.
Agent capabilities still require authorization and do not imply content-key access. A hosted
decrypting agent is a trusted plaintext endpoint, including its operator and model/provider path;
it is not operator-blind E2EE. Require explicit per-board feature enrollment, recipient/data-scope
disclosure and revocation semantics for any exception; never silently upload keys for convenience.

Slack already receives messages posted to it; its
[message events](https://docs.slack.dev/reference/events/message/) carry message content.
Plaintext Slack ingestion cannot pass through an operator-blind Sugarkube API/queue. It must use
a separately trusted user-controlled ingress endpoint that verifies, authorizes and encrypts
before transfer, or an explicitly disclosed weaker integration profile. Slack retains its own
copies. Sending decrypted content back to Slack is a new disclosure requiring audience and action
approval, not an automatic property of board membership. No plaintext webhook debugging logs.

Recommended option for the future E2EE roadmap, **not yet an accepted product choice**:
private-by-default boards, decrypting agents
on trusted user devices, and generic content-free Slack notifications linking to the encrypted
application entry without card IDs or titles. If inference uses a token.place pool, it must be an explicitly trusted LAN-only
endpoint set with scoped board disclosure and no cloud fallback, hidden telemetry or implicit
access to another private corpus. Those endpoints and their administrators join the plaintext
trust boundary. Sugarkube hosting remains ciphertext-only. Notifications must not expose titles,
snippets, attachments or decryption keys; even a generic link reveals activity/existence and needs
an approved destination audience, authenticated opening and no content-revealing unfurl.

An optional user-controlled gateway may give an explicitly authorized ChatGPT dot selected
plaintext while Sugarkube hosting holds ciphertext only. The gateway's control and key custody
must be independent of hosting; it locally unlocks approved scope, verifies the dot recipient,
enforces tenant-owner disclosure/tool grants and validates returned updates before encryption.
Locked, offline or unverified gateways block access. OpenAI becomes a trusted cloud recipient of
that selected content, outside an exclusively local guarantee; no universal keys or automatic
cloud fallback are supplied. Revocation stops future access, not previously disclosed copies.
Actual connectivity, authentication, scope and provider retention require qualification; this
route is not a credential/data-sharing authorization or a requirement for initial-mode dots.

For unattended local agents, explicitly authorize the board/action scope and lifetime of retained
local key/session material, its protected storage and revocation/lock behavior. It is not compatible
with a promise of a fresh password for every decryption. With password-on-every-unlock and no
retained unlocked session, processing pauses while locked and resumes only after local unlock.
Ordinary Slack intake remains an optional less-private path: Slack and its receiving endpoint see
plaintext, and later encryption cannot retroactively make that intake E2EE. Do not enable it merely
because a board has notifications. These future-mode choices require an explicit product decision.

No server master-key escrow or universal recovery password. Choose an explicit recovery
policy: user-held, independently stored high-entropy offline recovery material and/or a separately
reviewed verified-device or
authorized-member recovery mechanism. Define its board/history scope and recovery-key custody;
Sugarkube backs up opaque envelopes, not the client recovery secret. Account/password reset must
not manufacture missing decryption keys. Lose all usable keys/recovery paths and the data may be
permanently unreadable even with a perfect database restore. Test recovery before claiming it works.

An attacker who copies a wrapped key can guess passwords offline; API rate limits do not stop
that attack. Argon2id increases cost but cannot rescue a weak password or compromised endpoint.
Password changes rewrap local random key material; old wrappers retained in backups may still
be attacked using an old password. Suspected key disclosure needs key/epoch rotation and a
reviewed re-encryption policy, with honest retained-copy limits, not merely a password change.
Recovery secrets are highly privileged recipient keys, even when held by a user instead of a server.

## Optional E2EE platform acceptance (planned and unrun)

These cases add to the matrix below. Use synthetic content canaries and qualified test vectors;
no runtime, cryptographic or recovery test has been executed for this amendment. They gate the
optional E2EE mode, not the initial trusted-server implementation.

| Case | Required negative/recovery test and positive control | Owner |
| --- | --- | --- |
| Hostile infrastructure operator | Inspect API memory/logs, DB pages, WAL, replicas, snapshots, restored backups, object store, caches and support bundles; no plaintext canary or content/unlock key. Authorized verified client decrypts the same restored record | Sugarkube + Axel |
| Identity versus decryption | GitHub login, operator DB role, account reset and outer backup key cannot decrypt; legitimate member with locally unlocked keys can | Axel |
| Recipient substitution/enrollment | Replace directory key, add server-approved rogue device, replay old membership and forge device grants; trusted clients refuse unverified recipients. Verified enrollment succeeds | Axel |
| Rotation/history | Removed member fails to decrypt new epoch writes; authorized remaining member succeeds. Demonstrate that retained old keys still decrypt granted history and that an offline writer cannot silently publish under a revoked epoch | Axel |
| Envelope integrity | Swap tenant/board/object/chunk, author, epoch, version or nonce; truncate/reorder; repeated encryption nonce; malformed/oversized KDF parameters. Fail safely before display/action; qualified vectors and randomized encryption of repeated plaintext succeed without nonce reuse | Axel |
| Malicious client/update | Hosting operator serves modified/downgraded client or key-capture script; independent client rejects it. Test and clearly label weaker web delivery that cannot reject it | Joint |
| Offline guessing/recovery | Exercise wrong passwords, KDF floors/resource bounds, lost device, missing recovery material, old wrapper after password change and recovery-key compromise. Distinguish unreadable loss from recoverable ciphertext | Axel |
| Rollback/split view | Restore older valid ciphertext, key epochs, grants and consumed approvals; independent checkpoint detects mismatch. Reset device without a witness reports unknown freshness and blocks sensitive dispatch | Joint |
| Plaintext integrations | Route synthetic Slack text, search, validation, agent and attachment processing; operator-blind path never decrypts. Explicit trusted endpoint exception displays recipient/data scope and does not claim the strict profile | Joint |
| Local agent/notification option | Locked client pauses work unless scoped retained local authority was explicitly granted; deny cloud fallback and untrusted LAN recipients. Generic Slack payload/unfurl contains no content or keys; opening still requires identity, membership and local decryption | Joint |
| Legacy plaintext | Seed a synthetic pre-E2EE table, WAL archive, snapshot and support dump; migration inventory finds each residual. New ciphertext path passes, while retained old copies remain a declared exposure until disposition is verified | Sugarkube + Axel |

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

Neither PV/disk encryption nor a replicated storage layer provides client E2EE. Future-mode
capacity tests must account for encrypted attachments, key envelopes, padding and retained epochs; do not assume
plaintext compression, deduplication or server-side search indexes still apply.

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
independent encrypted off-site copies. PostgreSQL archives completed WAL segments: low write
traffic can otherwise leave acknowledged changes unarchived indefinitely. Require a bounded
`archive_timeout` (initial trial: 5 minutes) or a qualified streaming archive, with segment close,
upload/retry and off-site durable verification together below the 15-minute RPO. Verify a lone
synthetic commit after idle time is recoverable off-site within that bound, including delayed
uploads and retries. Measure last recoverable commit age rather than treating a running archive
process as proof. Warn before 10 minutes and page by 15; a transport outage exceeding the budget
is an RPO breach, not a met guarantee. Account for extra archive volume from forced segment
switches. Confirm retention, data deletion obligations and costs
with the owner. Use engine-consistent backups, authenticated transport, integrity manifests and
an outer archive-encryption layer with separately held infrastructure recovery keys. This layer
protects backup media. In initial mode, authorized recovery operators can decrypt database
contents; restrict and audit that authority rather than claiming operator blindness. In optional
E2EE mode, outer archive recovery does not decrypt client content: operators restore ciphertext
without client content/wrapping/recovery keys. That future mode must back up encrypted payloads,
key envelopes, epochs and necessary metadata together; missing envelopes can make otherwise
intact data unreadable. Archive writers must not delete older
backups; retention administration has a separate identity. Evaluate immutable retention against
privacy deletion requirements. PV snapshots alone are not sufficient; use supported consistency
coordination. PostgreSQL PITR depends on a valid base backup and an unbroken WAL sequence:
[official recovery guidance](https://www.postgresql.org/docs/18/continuous-archiving.html).

Rehearse monthly with synthetic data and after engine/operator/schema changes. Initial-mode
recovery measures obtaining infrastructure keys, provisioning, replay, membership/RLS, semantic
ID/history validation and HTTPS service restoration under the approved trusted-server boundary.
For optional E2EE, also rehearse crypto-format changes and report infrastructure ciphertext restore
time separately from authorized user recovery to readable content. That mode's full RTO includes
user-held key availability and independent freshness; operators cannot guarantee recovery of lost
client keys. Trusted synthetic clients validate decryption and authenticated history, returning
only sanitized outcomes to platform operators. Corrupt a
copy, remove WAL, deny keys and simulate unavailable backup storage; each must fail visibly.
Evidence contains checksums, versions, timings and counts only, not recovered content.

Recovery order: declare incident; fence all old writers and pause Slack/agent consumers; select
verified backup and release/schema pair; restore isolated volumes; validate integrity, tenant
access and completeness; validate history and authority freshness (with trusted-client key-epoch/
decryption evidence additionally required in future E2EE mode);
rotate exposed credentials if needed; invalidate old sessions and pending
capabilities; reconcile durable inbox/outbox deduplication; approve the new writer; switch DNS/
ingress with bounded cache assumptions; verify; resume bounded consumers. Never replay side
effects merely because a restored outbox says pending. Use external action reconciliation and
fresh approval where outcome is uncertain. Independently reestablish current revocations,
consumed capabilities and deletion restrictions against an authority freshness anchor outside
the restored data lineage. Its custody/protocol is an open joint decision; unknown freshness
blocks activation and dispatch. Keep the old cluster fenced during failback and
reseed it from the authoritative lineage rather than merging divergent histories.

## Schema, release integrity and legacy migration

Axel publishes reviewed migration checksums and required/current schema ranges with immutable
code revision, frontend artifact, image and chart digests through `ReleaseManifest v1`.
Its proposed authenticated `GET /api/v1/compatibility` exposes bounded API/schema compatibility
metadata; readiness/write availability remain distinct operational signals. Sugarkube's proposed
deployment receipt references the manifest digest and actual deployed schema/artifacts, and binds
environment, values digest, engine/operator versions, schema target, migration set and staging
test results. Tags alone are mutable references: resolve and record immutable identities and
refuse mismatches. A successful tag workflow does not establish a supported Sites publication
credential. External tagged release-to-Sites automation is unverified; keep an explicit manual
publication/verification gate until a supported mechanism is established.
The optional E2EE mode must additionally bind crypto-envelope versions, key-epoch compatibility
and independently verified client release identity. Hosting-controlled manifest signatures alone
do not establish trusted client delivery against that same operator; that mode requires a client
trust root separate from Sugarkube deployment authority.

No migrations on API startup. A single serialized, bounded migration job obtains a database lock,
checks starting schema and backup freshness, uses temporary migration authority and records its
result. Prefer expand/backfill/verify/contract across releases, bounded batches and dual-version
compatibility. Tenant columns/policies exist before any newly accessible data. A failed migration
blocks promotion; operators inspect recorded progress and use a reviewed idempotent forward
repair. App rollback is allowed only within the declared schema compatibility range. Destructive
schema rollback is not a Helm rollback: restore into isolation or repair forward with explicit
data-loss analysis and owner decision. Do not automatically restore over newer valid writes.
For optional E2EE, server migration jobs may change opaque storage/schema only; content
transformation/re-encryption occurs on authorized trusted endpoints, with no client keys mounted
in a migration Job. That mode tracks cipher/format compatibility separately from SQL schema and
rejects insecure downgrades. Initial-mode jobs retain separately authorized migration privileges.

Legacy migration is a separately authorized project: inventory current and archived sources;
create and verify encrypted snapshots; define canonical ID/provenance mappings; import into an
isolated target; reconcile counts, stable IDs, full ordered histories, timestamps, archive states,
references and content hashes; run tenant-isolation tests; rehearse cutover and rollback. Mapping
old owners to new tenant membership requires explicit verification, never inferred from imported
text. Keep approval history as display-only provenance outside executable capability records.
Freeze writes or capture a validated final delta, repeat reconciliation, obtain owner cutover
approval, then switch clients. Preserve the protected source for the approved retention window.
After new writes begin, rollback requires delta reconciliation; simply switching back loses data.

Before optional E2EE conversion, inventory legacy plaintext in tables, WAL, replicas, snapshots,
previous exports, logs, support bundles, attachment derivatives and off-site copies.
Encrypt and semantically reconcile on an authorized trusted client, preserving current and
archived IDs/history; operators validate ciphertext inventory and signed client outcomes only.
Do not upload plaintext to the new service as a staging step. Re-encrypting a live table does not
erase older WAL or backup copies. Keep protected legacy copies only under an explicit retention/
disposition policy, record their residual plaintext exposure, and verify disposal where possible.
Do not claim cryptographic erasure for plaintext or copies an operator/member may already retain.
An E2EE cutover claim applies to newly qualified paths, not retroactively to every historical copy.

## End-to-end threat model and proposed regression matrix

Assets include tenant content/history, identities, sessions, Slack installations, memberships,
approval capabilities, release evidence, secrets and recovery material. Adversaries include an
unauthenticated internet caller, a malicious tenant/member, forged or replayed Slack events,
prompt-injection authors, compromised API/agent/dependency, and a privileged operator or node.
Trust boundaries are browser/Sites-to-API, identity-provider callback, Slack ingress, queue/agent,
API-to-database, migration authority, CI-to-release, storage-to-backup, and recovery-to-live service.
The expanded model explicitly includes a malicious hosting/API/database/backup operator with
root access and control of responses, directories and served frontend code. Trusted client devices,
verified update roots and deliberately enrolled plaintext endpoints are separate trust boundaries.
Initial mode accepts privileged-operator content exposure while constraining ordinary access.
Optional operator-blind content confidentiality depends on independent trusted endpoints and
cryptographic qualification; these are not current implementation claims.

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
| Profile / authority separation | Online worker reaches sensitive corpus, local UI, inference or backups; stale restored approval matches old state but not independent freshness | No cross-profile access or egress; unknown freshness blocks activation/dispatch; joint |
| Failure / recovery | Primary loss; partition; one-node maintenance; disk corruption; total site loss; backup endpoint unavailable; lost recovery key | Single writer or explicit unavailable state; validated recovery timing/data bounds; no assumed second cluster; Sugarkube |

Slack implementation should follow [official request verification](https://docs.slack.dev/authentication/verifying-requests-from-slack/).
For the optional E2EE profile, plaintext verification/normalization occurs at the explicitly trusted ingress
endpoint described above, not a hosting-operated plaintext API or queue. Content-dependent cases
in that profile run at trusted endpoints; its server-only cases validate metadata and ciphertext.
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
Collect crypto/freshness failures as bounded reason codes; do not attach decrypted error inputs,
key material or full ciphertext dumps to alerts. Support cannot request unlock passwords or
universal tenant keys. Any user-authorized diagnostic plaintext export is a disclosed exception
with exact content/recipient scope. Initial-mode support still minimizes plaintext access;
optional E2EE support must remain ciphertext-only unless an explicit exception changes that boundary.

Proposed alerts: page on no safe writer, fencing ambiguity, archive age over 15 minutes or imminent
disk exhaustion; warn at 30% free disk, 80% connection utilization, missing daily backup or overdue
monthly restore. Validate thresholds against measured growth and acceptable noise. A separate
off-cluster heartbeat is needed to notice total cluster loss. Alert tests must verify routing,
deduplication and recovery notification with synthetic events before enabling production.

Implementation may begin only after both design PRs are owner-merged and a separate scope is
approved. Then require engine/operator/storage selection, measured spare capacity, supported
ARM64 artifacts, agreed RPO/RTO and retention, exact API/release interfaces, DNS/TLS ownership,
applicable initial-mode negative tests implemented with recorded outcomes, and a restored synthetic staging rehearsal.
Production import requires its own protected backup and reconciliation/cutover approval.
Initial-mode gates additionally require an explicit processor/data-flow inventory, tenant-scoped
agent/Slack enrollment, key-management qualification and honest privileged-operator exposure.
Only adoption of the optional E2EE extension depends on vetted cryptographic protocols/libraries,
independent client/update trust, recipient verification, enrollment, rotation/history grants,
metadata/freshness/recovery policies and future local-agent/Slack/unlock decisions. Track those
in the single Axel roadmap issue. They do not block the initial trusted-server mode. Publication
requires documentation CI and review evidence for the actual revised head; those checks do not
prove runtime or cryptographic qualification.

Residual risks: a compromised API/operator can bypass metadata access controls, deny service,
delete data, lie about durability, or replay/split views. Initial mode also exposes content to
privileged trusted-server/integration operators; at-rest encryption does not remove this risk.
Only a separately qualified future E2EE path aims to withhold content from hosting operators.
A compromised client/update signer, enrolled plaintext
endpoint or authorized member can expose content. Weak passwords permit offline guessing; key
loss can defeat recovery; rotation cannot revoke old copies or past plaintext. RLS/TLS/access
controls remain defense in depth, not E2EE substitutes. Memory-unsafe dependencies, shared-site
failures, visible metadata/timing, legacy plaintext retention, unverified freshness, noisy
neighbors, ambiguous external effects and recovery mistakes remain. No attack-proof system is promised.
ChatGPT sign-in eligibility, Sites publication automation, second-cluster independence, exact
capacity and recovery performance are unresolved. No risk here is declared mitigated by prose.
