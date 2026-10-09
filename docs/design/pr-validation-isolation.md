---
personas:
  - software
---

# Pull request validation isolation design

## Status and decisions

This is a design-only proposal for Sugarkube's automated pull request validation and review
boundary. It defines future behavior and acceptance evidence. It changes no workflow, wrapper,
runtime, credential, permission, or deployment. No sandbox canary or live workflow was executed
for this proposal, and no remediation or demonstrated credential leak is claimed.

The design fixes three policy choices:

- Use dependencies prepared from an immutable trusted base. Reject pull request changes to
  dependency or preparation inputs from this lane until separately reviewed.
- Keep review read-only. Repair must be a separately authorized job with a separate lifecycle.
- Bind preparation, validation, review, and result consumption to the exact approved head and
  base. Abort on stale identity; head or base changes require renewed approval.

The runtime choice remains **open for review**. The recommendation is a disposable validation VM
with externally enforced isolation and a credentialed controller outside the guest. Hardened
Bubblewrap on a dedicated disposable validation runner is an alternative, subject to the same
acceptance contract and explicit acceptance of its shared-kernel boundary. Neither runtime has
been selected or implemented by this document.

The companion [offline acceptance contract](pr-validation-isolation-acceptance.md) is a future test
plan. Every case is currently unexecuted.

## Verified source observations

Source was reviewed on 2026-10-09. Sugarkube main was
`76be137adb2f41aa111bc386f927ca06a0cdaa4d`; Gabriel main was
`45540a1108ae6523ae679c743d2bf18147190610`. The following observations are source-level findings,
not evidence that an attacker exercised them or that a particular runner exposed credentials.

1. **Preparation precedes the demonstrated containment.** Sugarkube checks out the authorized PR
   SHA and invokes `prepare-deps` from that workspace before installing Bubblewrap. Its trusted
   wrapper conditionally invokes the workspace's `scripts/install_just.sh`. Later lint and test
   operations run the wrapper directly; the wrapper does not establish an OS sandbox. The explicit
   Bubblewrap call encloses the network probe alone. See the pinned
   [workflow](https://github.com/futuroptimist/sugarkube/blob/76be137adb2f41aa111bc386f927ca06a0cdaa4d/.github/workflows/claude.yml#L106-L202)
   and [wrapper](https://github.com/futuroptimist/sugarkube/blob/76be137adb2f41aa111bc386f927ca06a0cdaa4d/.github/scripts/claude-validate.sh#L36-L106).

2. **Gabriel has the analogous preparation and probe-only boundary.** Its wrapper consumes
   workspace `requirements.txt` and runs `npm ci` before the validation job installs Bubblewrap.
   Later checks invoke the wrapper directly. Its separate Claude job also invokes preparation
   before creating the action settings, and that job grants `id-token` write permission. The code establishes
   execution order, not actual OIDC exchange or token theft. See the pinned
   [workflow](https://github.com/futuroptimist/gabriel/blob/45540a1108ae6523ae679c743d2bf18147190610/.github/workflows/claude.yml#L106-L253)
   and [wrapper](https://github.com/futuroptimist/gabriel/blob/45540a1108ae6523ae679c743d2bf18147190610/.github/scripts/claude-validate.sh#L34-L72).

3. **Authorized SHA and later review checkout are different contracts.** Sugarkube records a PR
   head and validates that SHA, but the pinned action's open-PR branch handling subsequently fetches
   and checks out a branch name. That path does not compare the checkout against the workflow's
   authorized SHA. A moving branch can therefore make the earlier validation insufficient evidence
   for the later checkout; no race was executed here. See the
   [authorization output](https://github.com/futuroptimist/sugarkube/blob/76be137adb2f41aa111bc386f927ca06a0cdaa4d/.github/workflows/claude.yml#L90-L101)
   and [pinned branch handling](https://github.com/anthropics/claude-code-action/blob/fa7e2f0a29a126f0b81cdcf360561b36e44cf608/src/github/operations/branch.ts#L173-L217).

4. **The claimed `INPUT_*` credential leak is unsubstantiated.** GitHub documents that composite
   actions do not automatically receive input environment aliases. This pinned composite action
   explicitly maps conventional credential variables, `OVERRIDE_GITHUB_TOKEN`,
   `DEFAULT_WORKFLOW_TOKEN`, and `ALL_INPUTS`. Its SDK setup copies the parent environment and
   removes the two OIDC request variables. Those facts identify surfaces to verify; they do not
   establish what the pinned CLI exposes to every subprocess or tool. Missing `INPUT_*` deny
   entries alone do not prove a leak. See
   [GitHub input semantics](https://docs.github.com/en/actions/reference/workflows-and-actions/metadata-syntax#inputs),
   [explicit action mappings](https://github.com/anthropics/claude-code-action/blob/fa7e2f0a29a126f0b81cdcf360561b36e44cf608/action.yml#L277-L325),
   and [SDK environment setup](https://github.com/anthropics/claude-code-action/blob/fa7e2f0a29a126f0b81cdcf360561b36e44cf608/base-action/src/parse-sdk-options.ts#L275-L287).

Existing trusted-actor and same-repository guards, read-only validation permissions, and
`persist-credentials: false` reduce exposure. This proposal does not establish a fork-triggered
exploit, inspect repository variables or relying-party policies, or claim that a read-only job
contains no host-side credentials. The
[Sugarkube guards and checkout settings](https://github.com/futuroptimist/sugarkube/blob/76be137adb2f41aa111bc386f927ca06a0cdaa4d/.github/workflows/claude.yml#L18-L135)
remain relevant to interpretation.

The jobbot3000 wrapper is a reference for fixed operations, cleared environment, restricted mounts,
and contained validation. At reference `9edd63a3ec457d97075af6fbb4839428cb0b7fd8`, its wrapper Git blob
is `eebf48cfa619744661ed2164adc17775321179b5`. Main had advanced to
`eb4d1e653a5d41cef281c8d33b71e052049a5412` at review, but the wrapper and Claude workflow blobs were
unchanged. Reuse requires independent acceptance evidence; this proposal does not certify that
wrapper or claim active command injection. See the
[reference wrapper](https://github.com/futuroptimist/jobbot3000/blob/9edd63a3ec457d97075af6fbb4839428cb0b7fd8/.github/scripts/claude-validate.sh#L23-L108).

## Threat boundary and trust assumptions

Treat PR source, tests, dependency declarations, configuration, filenames, symlinks, repository
instructions, and generated output as untrusted. Tests, import hooks, build backends, package
lifecycle scripts, and tool configuration can all cause code execution. An authorized requester
does not make every byte of the requested PR trusted.

The trusted computing base consists of the immutable controller, authorization logic, source
exporter, dependency preparer, containment launcher, result verifier, approved runtime image,
and their pinned dependencies. The platform and kernel or hypervisor remain trusted. A runtime
escape or compromise of these components remains a residual risk requiring security response.

All PR-code execution must occur inside the validation boundary, including nested children and
grandchildren. Read-only review consumes immutable source as data; it cannot execute repository
code, load project plugins, launch package managers, or invoke a repair tool. Prompt text and
model tool allowlists are defense in depth, not the OS isolation boundary.

The boundary protects host files, runner services, credentials, other jobs, and the integrity of
the result controller. It does not prove that PR-controlled tests are honest or that passing tests
make the patch safe. Trusted required checks and the containment canaries have independent
identities outside the PR's writable tree.

## Architecture and data flow

### Trusted authorization and source preparation

A trusted controller resolves the repository, PR, open state, authenticated request, head commit,
base commit, and workflow/policy revision. It constructs an approval record for that exact tuple
and permitted operation set. The record is controller-owned and integrity protected; a JSON file
supplied by the PR cannot authorize execution.

The source exporter fetches exact commits and produces a bounded source bundle without executing
hooks, submodules, LFS filters, text-conversion drivers, or repository scripts. Submodules and LFS
objects require an explicit future policy; unsupported inputs are rejected. Export and extraction
must reject path traversal, absolute entries, device files, unsafe links, and oversized archives.
Control files, Git credentials, runner command files, and controller configuration are excluded.

Trusted setup occurs in a clean location with trusted binaries and configuration. No interpreter
starts from a PR directory before containment. PR `PATH`, `PYTHONPATH`, `NODE_OPTIONS`, `.env`,
startup hooks, Git configuration, and package-manager configuration cannot influence preparation.
The runtime and wrapper are ready and verified before any tool can execute PR-controlled code or
load executable project configuration.

### Dependency preparation

Prepare dependencies from the approved trusted-base commit in a separate, short-lived preparation
environment. Use an immutable toolchain manifest with pinned versions, platform identity, and
integrity digests. If the base lacks a reproducible manifest, mark the lane blocked until one is
reviewed; do not silently resolve floating versions and call them pinned.

Dependency input comparison happens before any PR installation or execution. The protected set
includes lockfiles, dependency declarations, requirements/constraint includes, build backends,
installer scripts, package-manager configuration, and preparation-affecting workflow or wrapper
files. Reject additions, deletions, renames, symlink substitutions, and transitive include changes.
The trusted policy defines the set; a PR cannot narrow it. A change requires a separate dependency
review and a new approved preparation identity before this lane can run.

For Node dependencies, preparation disables lifecycle scripts and uses the trusted lockfile and
trusted registry configuration. A script-disabled install does not make later `npm run` or tests
non-executable; those belong inside validation. This distinction follows the
[npm command documentation](https://docs.npmjs.com/cli/v11/commands/npm-ci/#ignore-scripts).

For Python, require hashes and approved prebuilt wheels; reject source distributions, editable
installs, VCS/direct-URL substitutions, and unreviewed build backends. Wheel availability failures
are blockers, not permission to build on the controller. These controls follow
[pip's secure-install guidance](https://pip.pypa.io/en/stable/topics/secure-installs/).
Installed packages can execute when imported, so their use remains contained.

The dependency environment receives no repository write token, AI credential, or OIDC capability.
If registry downloads are required, a separately constrained fetcher accepts only destinations and
digests from the trusted manifest; it cannot read PR files or accept PR-derived URLs. Private
registry authentication and source builds are outside this initial design. Export only a
content-addressed dependency bundle and a controller-recorded manifest. Never restore a
PR-writable cache into trusted preparation or review.

### Credentialless validation

The controller launches a fresh containment instance for each fixed operation, passing only the
exact source bundle, read-only dependency bundle, trusted wrapper, minimal runtime, and bounded
operation identifier. Use a clean writable work copy when a test requires writes; the canonical
source bundle remains immutable. Work copies and caches are not reused across operations or PRs.

The workload receives no GitHub token, OIDC request capability, model credential, runner artifact
credential, cloud credential, host home directory, or host service socket. This is an input and
isolation contract, not a claim that the outer Actions runner has no credentials. Control-plane
credentials remain outside its process, mount, network, and result-signing boundaries.

The launcher accepts enumerated operations and typed, bounded arguments. It never evaluates a
caller-supplied shell string. A PR cannot replace the launcher, select its policy, choose its
mounts, or assert that it is already contained through an environment marker. Containment is
established before any command that can load PR code or configuration.

### Static review and separate repair

Review is a separate job consuming the same approved immutable source and verified result record.
No PR dependency preparation or test execution occurs in the credentialed review process.
Repository instruction files, hooks, plugins, MCP configuration, startup settings, and helper
scripts are read only as data. Project/local tool configuration must not be loaded implicitly.

If an external model is used in a future implementation, an approved broker owns the model
credential and supplies only the bounded source/review input. Its tool surface is static and
read-only. A separate deterministic publisher can post an authorized review; it holds the minimum
posting capability and receives no executable artifact. Review cannot mint a write token, commit,
push, merge, dispatch, deploy, change settings, or start repair. A model's Bash network restriction
does not constrain parent-process APIs or MCP tools; each of those must be separately absent or
denied. No model or paid review invocation is requested by this document.

Repair, if separately authorized later, gets its own approval record, isolated workspace, allowed
paths, credentials, and publication gate. Any produced commit starts a new approval/validation
cycle. A review request, review comment, or generated suggestion cannot authorize repair.

## Runtime options for review

### Recommended separately enforced disposable environment

Use a fresh VM or microVM dedicated to untrusted validation, with source and dependency inputs
delivered before execution and a small trusted controller outside the guest. Disable guest access
to provider metadata, host control sockets, shared credentials, shared host filesystems, and
external networking. Export results through a bounded data-only channel whose receiver treats
every guest byte as untrusted. Terminate the whole instance after the operation.

This reduces reliance on isolating hostile code from a credentialed sibling process on the same
kernel. It adds image maintenance, startup cost, scheduling, and result-transfer complexity. A
disposable machine still needs network, storage, metadata, and controller isolation. Firecracker,
for example, explicitly leaves guest egress filtering to the host in its
[design documentation](https://github.com/firecracker-microvm/firecracker/blob/main/docs/design.md#threat-containment).
That project is an example, not a selected provider or implementation.

Do not assume a normal ephemeral Actions job meets this contract: the runner application and
other tooling execute within it. Nested VMs on GitHub-hosted runners are currently experimental
and unsupported, according to
[GitHub's runner documentation](https://docs.github.com/en/actions/concepts/runners/github-hosted-runners).
Platform support, cost, lifecycle ownership, and external enforcement must be reviewed before this
option can become an implementation plan.

### Alternative hardened Bubblewrap

Use a trusted launcher on a dedicated disposable validation runner, with private mount, user,
PID, IPC, UTS, and network namespaces; a minimal immutable filesystem; no inherited descriptors;
an empty environment followed by a short allowlist; no new privileges; dropped capabilities; and
reviewed syscall/resource restrictions. The controller and its credentials must not be reachable
from the workload even though the kernel is shared. Do not mount the host root, home, Actions
directories, service sockets, or broad writable host paths.

This is closer to the existing Linux workflow and can be less expensive to operate. Its launcher,
mount policy, kernel compatibility, and shared-kernel exposure require careful review. The
[Bubblewrap project](https://github.com/containers/bubblewrap#sandbox-security) places responsibility
for the actual security policy on the caller. A fake-Bubblewrap argument test or a network probe
alone cannot prove the complete boundary. Lack of required namespaces or sandbox support must
fail closed; it must not trigger unsandboxed fallback or an automatic host security-setting change.

### Decision gate

Before implementation, select one runtime, document its exact versions and enforcement owner,
confirm a supported host, agree resource limits, and review the residual risk. Both options must
pass the same offline contract on the actual selected boundary. A provider label, container label,
or successful job conclusion cannot substitute for this evidence.

## Required isolation properties

- **Network:** deny guest/workload egress before PR execution, including IPv4, IPv6, DNS, proxies,
  loopback access to host services, link-local metadata, and inherited sockets. Local services
  wholly inside the isolated workload may be allowed for tests. No host socket or network bridge
  may provide an alternate path. Internet-dependent checks are unsupported in this initial lane.
- **Filesystem:** expose only immutable source/runtime/dependencies and per-operation scratch or
  output directories. Canonicalize and constrain paths at consumption time, reject unsafe links,
  and prevent writes to trusted policy, input bundles, result envelopes, and future operations.
  A read-only host-root mount is prohibited because it still exposes host data.
- **Processes:** prevent host PID visibility, signal/ptrace access, namespace re-entry, terminal
  injection, inherited file descriptors, and access to control-plane IPC. All descendants remain
  contained. External limits cap wall time, memory, process count, CPU, output, and disk use;
  limits cannot be raised by PR code. Cancellation kills and reaps the entire operation.
- **Secrets:** construct the workload environment from an allowlist rather than a denylist. Exclude
  aliases, serialized action inputs, credential files, agent sockets, and runner command channels.
  No secret is intentionally passed and then entrusted to redaction. Dummy-only tests separately
  exercise conventional names, `INPUT_*`, `OVERRIDE_GITHUB_TOKEN`, `DEFAULT_WORKFLOW_TOKEN`,
  `ALL_INPUTS`, OIDC names, files, descriptors, and process surfaces.
- **Result integrity:** the controller observes process lifecycle and containment outcome outside
  PR control. Workload output cannot set authoritative status, replace the trusted required-check
  list, forge GitHub workflow commands, or alter an approval record.

## Exact identity and result consumption

The approval and result tuple contains repository identity, PR number, approved head SHA, approved
base SHA, trusted workflow/policy SHA, operation-set digest, dependency-bundle digest, runtime
image/policy digest, run identity, attempt, and bounded approval validity. Store authenticated
approver evidence in the controller's access-controlled record; public summaries need only a
non-sensitive reference. Hashes bind content but do not authenticate a producer by themselves.

Approval has explicit `valid_from` and `expires_at` values enforced using the trusted controller's
clock. Before implementation is enabled, the policy must specify a numeric maximum approval
lifetime and allowed clock skew. Missing values, future-dated approval beyond that tolerance,
expiry, or an unverifiable clock block execution and publication. Expiry is checked at launch,
review consumption, and publication; a long-running operation cannot extend it. A changed head or
base still requires renewed approval even within the original lifetime.

The controller owns a per-repository/PR generation and exclusive execution lease in trusted state.
Creating a newer approved generation supersedes the old one and requests cancellation of its
work. Every result transition and publication attempt must atomically compare the active
generation, full tuple, lease owner, approval validity, and expected prior state before changing
current-result eligibility. Old or lease-lost controllers can retain immutable historical records
but cannot promote, overwrite, or re-authorize the current result. Duplicate deliveries and retries
use an idempotency key containing generation, run, and attempt; conflicting payloads are rejected.
All publishers use this single eligibility controller rather than independently updating a shared
current-success comment or status. Publication reconciles after the external API call, because
GitHub ref changes and controller transactions cannot be made one atomic transaction.

Lease expiry does not prove workload teardown. The policy must define numeric lease, heartbeat,
cancellation, and teardown deadlines before implementation is enabled. A superseded or crashed
controller's workload remains quarantined until an independent watchdog proves teardown; neither
a new generation nor a cleanup retry may reuse that instance first.

Require the following sequence:

1. Resolve current head/base and create or verify the exact approval record. Preserve same-repo
   and requester checks. Reject closed/merged PRs and unsupported event types.
2. Fetch/export the immutable commits, verify content identities, compare protected inputs, and
   prepare the trusted-base dependency bundle. Do not resolve a branch name again for execution.
3. Immediately before launch, re-read the PR and verify both head and base still match. On change,
   return `stale` and require renewed approval. A rerun does not inherit approval for changed refs.
4. Execute all required operations in the selected boundary. The external controller records
   operation identity, exit status, timeout/cancellation, boundary checks, and output digests.
5. Before review consumption and any publication, authenticate the exact producer/workflow and
   run attempt, verify the tuple and artifact digest, reject duplicate or conflicting results,
   and re-read current head/base. Bind any review or check to the exact head SHA. Reject results
   from another repository, PR, run, attempt, base, policy, or dependency set.
6. If head/base moves during publication, treat the result as historical for its exact tuple and
   withdraw its eligibility for the current PR. Reconcile immediately after publishing; do not
   describe an earlier commit's success as current. A future merge gate must also compare the
   tuple at its decision point. This proposal authorizes no merge mechanism.

An action that internally checks out a moving branch cannot satisfy this design through an
outer checkout or a late SHA check alone. Choose an integration that consumes immutable source
without changing refs, or revise and separately verify that integration before adoption. A
post-action comparison cannot undo prior execution against the wrong source.

Artifact names containing a SHA are only labels. Consumers must authenticate provenance and
check the record rather than trust the name. Treat every log and guest-produced file as untrusted
data; apply size limits, strict schemas, safe extraction, and no executable deserialization.
GitHub similarly cautions about cross-workflow artifacts in its
[secure-use guidance](https://docs.github.com/en/actions/reference/security/secure-use#mitigating-the-risks-of-untrusted-code-checkout).

## Result states and logging

Authoritative terminal states are `passed`, `failed`, `blocked`, `stale`, and `cancelled`.
`passed` requires every required operation to complete successfully for the same tuple, all
boundary checks to pass, and cleanup to be verified. Missing, skipped, timed-out, cancelled,
unsupported, or ambiguous results never count as passed. An AI action's success or fluent summary
is not validation evidence.

Keep informational lint results separate from required checks. Sugarkube currently distinguishes
informational lint from hard-failing tests in its
[workflow](https://github.com/futuroptimist/sugarkube/blob/76be137adb2f41aa111bc386f927ca06a0cdaa4d/.github/workflows/claude.yml#L157-L224).
This design does not silently promote lint debt into a new merge gate. The trusted operation-set
manifest must explicitly identify required and informational checks; containment failures always
block the lane. Static diagnosis of a failed validation can continue only as clearly labeled
read-only analysis, without claiming successful validation or enabling repair.

Public output is a bounded summary: source identities, tool/runtime identity, operation names,
terminal state, elapsed time, and sanitized error categories. Do not dump environments, action
inputs, request headers, raw model transcripts, arbitrary archives, or host paths. Escape control
characters and workflow-command syntax; do not stream untrusted output as runner commands. Raw
diagnostic capture and upload are disabled in the initial lane. If later needed, they require a
separately reviewed access/retention policy and must exclude secrets.
Unexpected secret-like output is quarantined, not copied into a public review. Redaction and
masking are secondary safeguards.

Before implementation is enabled, specify numeric maximum retention periods for controller audit
records, sanitized evidence, quarantined output, and disposable storage, plus the authorized reader
roles and enforced deletion mechanism for each. Missing policy blocks capture/publication; it does
not imply indefinite retention or public artifact access. Cleanup and retention failures must be
observable and owned by the runtime operator. Public GitHub summaries may persist under platform
retention, so they must contain only the public-safe fields above; the design cannot promise that
published content can later be recalled.

## Failure handling and rollback

- Missing runtime support, mount/namespace setup failure, invalid approval, identity drift, or
  dependency-policy mismatch stops before PR execution. Record a bounded reason.
- A failed canary, unexpected network path, host visibility, or control-plane access cancels the
  workload and invalidates its result. Preserve minimal safe evidence for review.
- Timeout, cancellation, resource exhaustion, or cleanup uncertainty prevents a passing result.
  A watchdog outside the workload must terminate descendants or the whole VM. An unverified
  cleanup blocks instance reuse and must be escalated to the runtime operator.
- Transfer, schema, provenance, or digest failures reject the artifact. Do not rerun an untrusted
  helper on the controller to repair it. Retries retain exact identity and policy; changed inputs
  need new approval.
- Future rollback disables the new automated execution lane and invalidates incomplete/stale
  results. Keep static/manual review available. Do not roll back by re-enabling uncontained PR
  execution. Runtime image or dependency rollback requires a reviewed pinned identity and the
  same acceptance evidence.

No existing workflow is disabled, reverted, or otherwise changed by this document.

## Implementation and evidence gate

Implementation is a separate review after runtime selection. Its bounded scope should cover the
trusted preparation manifest, source/approval binding, isolated operation launcher, static-review
adapter, result verifier, and offline harness. Gabriel can adopt the shared contract in a separate
change; jobbot3000 is a regression reference only. This Sugarkube proposal includes no cross-repo
implementation.

Before enabling any future lane, require:

- Reviewed runtime selection, dependency-policy inventory, required-operation manifest, and
  controller/result provenance design, including atomic eligibility and generation ownership.
- Explicit numeric approval/clock, lease/heartbeat, cancellation/teardown, resource, and retention
  policies, with access roles and lifecycle ownership. These values remain an implementation gate;
  this design does not silently supply permissive defaults.
- Passing real-boundary evidence for every mandatory case in the companion contract, using only
  synthetic source and dummy credentials. Fake-runtime tests alone are insufficient.
- A pinned CLI/tool-permission verification result if an agent CLI is retained. Unsupported
  offline behavior is reported as blocked, with live testing considered separately.
- A documented operator for image maintenance, incident handling, cleanup, and rollback.
- Separate approval for implementation, workflow changes, real-credential integration, or live
  operation. Acceptance of this design does not perform or authorize those actions.
