---
personas:
  - software
---

# Offline validation isolation acceptance contract

## Status and scope

This is the future acceptance plan for the
[pull request validation isolation design](pr-validation-isolation.md). **No case below has been
executed for this proposal.** This file contains no executable harness and establishes no
remediation, exploit, credential leak, or operational readiness.

The harness will use synthetic repositories, dummy secret markers, local fixtures, and the selected
pinned runtime in a disposable no-credential environment. It must never receive real GitHub,
OIDC, registry, model, cloud, or production credentials. It must not dispatch a repository workflow,
contact an external model, request a paid review, or probe public services.

Offline fixtures may include a local parent-side network listener, DNS fixture, synthetic metadata
endpoint, and host-side dummy files or sockets. These belong to the test environment, with no route
to the internet or real services. Denial tests need positive controls showing the fixture works
from the permitted harness side; connection failure alone is insufficient evidence.

## Evidence requirements

Every case records a versioned case ID, fixture digest, implementation commit, runtime/image and
policy digest, dependency digest, head/base tuple, expected result, actual result, bounded failure
category, and controller-observed cleanup. Evidence is produced outside the workload's writable
domain. Each assertion includes a positive control or distinguishes an unavailable fixture from a
passed denial. Do not publish dummy values unnecessarily; retain marker IDs and observed booleans.

Use these result labels: `not-run`, `passed`, `failed`, `blocked`, and `inconclusive`. An unavailable
kernel feature, unsupported CLI path, absent fixture, or missing trusted observation is never a
pass. A case passes only on the final implementation and exact pinned boundary being proposed.

## Preparation and execution order

- **PREP-01 Lifecycle sentinels.** Supply synthetic npm preinstall/install/postinstall/prepare,
  Python build-backend/setup, import/startup hooks, and installer-script sentinels. Trusted
  preparation must not execute PR-controlled sentinels. Intentionally executed test/config
  sentinels must first become observable inside containment, never on the parent.
- **PREP-02 Protected input changes.** Modify, add, delete, rename, or symlink a dependency,
  lockfile, constraints include, registry/configuration file, build backend, installer, trusted
  wrapper, or preparation policy input. Reject the execution request before installing PR
  dependencies. A separately approved new baseline must get a new preparation identity.
- **PREP-03 Reproducible dependencies.** An unknown digest, missing wheel, source distribution,
  floating dependency, registry redirect outside policy, incompatible platform, or missing
  transitive pin must block preparation. Do not fall back to source builds, alternate registries,
  or PR configuration. Use preloaded local fixtures; no registry calls occur in this harness.
- **PREP-04 Startup and cache poisoning.** Place hostile `.env`, package-manager config, Git
  filters, `sitecustomize.py`, `.pth`, shell startup files, and fake binaries in PR input. Seed a
  PR-writable cache. Trusted preparation must not load them. Restore only authenticated trusted
  dependency input; give every operation fresh mutable state.
- **PREP-05 Source extraction.** Archives with absolute paths, traversal, unsafe hardlinks or
  symlinks, device entries, unsupported submodules/LFS references, and excessive expansion must
  be rejected without modifying trusted paths or executing filters/hooks.

## Workload boundary

- **BOUND-01 Real containment.** With the actual selected runtime, observe the intended mount,
  process, network, user/privilege, and IPC boundary externally. Missing runtime or required kernel
  support must block launch before any PR sentinel runs. A fake executable recording arguments is
  useful as a unit test but cannot satisfy this case.
- **BOUND-02 Environment and serialized inputs.** Seed the parent with distinct dummy markers in
  conventional token names, synthetic `INPUT_*` names, `OVERRIDE_GITHUB_TOKEN`,
  `DEFAULT_WORKFLOW_TOKEN`, `ALL_INPUTS`, and OIDC request names. The workload, nested interpreters,
  child, and grandchild must see only the approved allowlist and no dummy marker. Test serialized
  data separately from variable-name matching.
- **BOUND-03 Files and processes.** Put markers in a synthetic host home, credential files, action
  directory, runner command-file directory, parent environment, open descriptors, and parent
  working directory. Attempts through `/proc`, fd paths, symlinks, hardlinks, or traversal must
  not expose them. Host-process signaling and ptrace attempts must fail without affecting the
  parent. Ordinary access to the permitted source and scratch paths must still work.
- **BOUND-04 Network paths.** Attempt IPv4/IPv6, DNS, HTTP/proxy, parent loopback, synthetic
  link-local metadata, abstract/path Unix sockets, and inherited socket access. The permitted
  parent fixture must record no workload connection or data. Test a contained loopback fixture
  separately if local test servers are allowed. No probe targets a real metadata or public endpoint.
- **BOUND-05 Writes and mounts.** Attempts to alter trusted policy, wrapper, runtime, dependency
  bundle, canonical source, approval record, or authoritative result record must fail. Writes to
  bounded scratch/output must succeed. A later operation starts from the original immutable
  input, unaffected by the earlier operation's workspace or cache.
- **BOUND-06 Descendants and resources.** Spawn only bounded synthetic children, then exercise
  timeout, cancellation, process count, memory, CPU, disk, and output limits. Verify limits are
  external to workload control and every descendant is gone. Simulated cleanup failure must
  prevent success and reuse. Do not use unbounded resource-exhaustion payloads.
- **BOUND-07 Invocation policy.** Unknown operations, extra arguments, absolute/traversal paths,
  options disguised as filenames, and attempts to bypass a trusted entrypoint must fail closed.
  Test shell composition, redirection, expansion, and wildcard forms at any CLI permission layer
  that remains. No forbidden form may reach an uncontained interpreter. A claimed internal
  containment environment flag or argument cannot bypass launcher checks.

## Review and repair separation

- **REVIEW-01 Static-only review.** Synthetic repository instructions, hooks, project/local
  settings, plugins, MCP configuration, and malicious result text must not start a subprocess,
  package install, network request, repository write, or repair. Use a deterministic local model
  stub if needed; do not call an external model service.
- **REVIEW-02 Parent tool boundary.** Verify the actual review adapter exposes no commit, push,
  merge, dispatch, deployment, settings, or token-minting capability. Test broker/publisher
  interfaces independently from shell denial. Static reads must be restricted to the approved
  source and result tuple. A model-generated tool request is untrusted input.
- **REVIEW-03 Separate repair approval.** A review trigger, PR comment, generated suggestion,
  approval for an older head, or validation success must not start repair. Simulated separate
  approval is bound to exact allowed paths and head/base. A simulated repair commit invalidates
  prior validation and requires a new cycle.
- **REVIEW-04 Pinned CLI behavior.** If implementation retains the historically pinned action/CLI,
  independently verify credential aliases, serialized inputs, settings sources, compound command
  rules, and tool boundaries on the actual pinned binary without real credentials or provider
  calls. The referenced action defaults to CLI `2.1.217` in its
  [base action](https://github.com/anthropics/claude-code-action/blob/fa7e2f0a29a126f0b81cdcf360561b36e44cf608/base-action/action.yml#L142-L156).
  If that binary cannot exercise a required path offline, record `blocked`; do not infer it from
  current documentation, source-only inspection, or a mock. Consider a static adapter that does
  not depend on that path, or seek separate authorization for a bounded verification phase.

## Exact identity and result gates

- **IDENTITY-01 Moving head or base.** Move synthetic refs after approval, during preparation,
  before launch, during validation, before review, and around publication. Every changed tuple
  becomes stale; no branch re-resolution silently changes execution input. Require renewed
  approval. Historical results remain labeled with their old immutable tuple.
- **IDENTITY-02 Checkout and event mismatch.** Supply another PR, repository, closed PR, unsupported
  event, mismatched detached checkout, merge-ref substitution, or workflow/policy revision. The
  controller must reject it. No non-PR issue path may bypass the PR approval contract.
- **IDENTITY-03 Result substitution.** Supply a same-named artifact from another run/attempt, a
  forged JSON approval, a modified digest, unauthenticated producer, duplicate/conflicting record,
  stale base, expired approval, or replayed result. Reject before static review consumption or
  publication. A matching artifact filename or checksum alone must not authenticate provenance.
- **IDENTITY-04 Required operations.** Simulate skipped, absent, failed, timed-out, cancelled,
  unsupported, truncated, or inconclusive required operations. None can become `passed` through
  `always()`, continuation-on-error, an AI success conclusion, or a forged log line. Explicitly
  informational lint must remain informational while boundary violations still block the lane.
- **IDENTITY-05 Untrusted test reporting.** Have PR tests emit fabricated success and attempt to
  modify operation status. The trusted controller must preserve actual operation/boundary
  observations and reject forged envelopes. Document that passing PR-controlled tests still
  supplies no guarantee of test honesty or patch safety.
- **IDENTITY-06 Concurrent generations.** Race duplicate delivery, two controllers, a new approved
  generation, lease loss, and delayed publication retries. Only the active generation/lease owner
  may atomically change current-result eligibility. The old controller cannot overwrite a newer
  result or regain eligibility. Verify idempotent same-attempt retries, rejection of conflicting
  payloads, cancellation of superseded work, and post-publication reconciliation when refs move
  across the external API call.
- **IDENTITY-07 Approval and clock limits.** Test just before, exactly at, and after expiry at
  launch, review consumption, and publication. Test future dates, tolerated/excessive clock skew,
  a run outliving approval, and absent numeric policy. Expired or unverifiable approval cannot
  execute, publish as current, or be extended by a retry. A fresh approval for a changed tuple
  creates a new generation without reviving old results.

## Output and lifecycle

- **OUTPUT-01 Safe parsing.** Oversized files, malformed schemas, executable serialization,
  path-bearing archives, unsafe links, and control characters must be rejected or safely bounded.
  Extraction and parsing must never execute guest output or write outside the quarantine area.
- **OUTPUT-02 Minimal logs.** Synthetic secret markers, serialized action inputs, workflow-command
  strings, fake annotations, raw headers, and host paths must not reach public summaries or alter
  runner state. A sensitive-looking output yields a bounded category and quarantine, without
  echoing the offending value. Prove the log reader does not interpret guest text as commands.
- **LIFE-01 Teardown.** Success, failure, cancellation, controller interruption, and publication
  error all trigger externally supervised teardown. A missing cleanup observation prevents a
  passed result and resource reuse; it cannot be repaired by trusting a guest's cleanup claim.
  Exercise lease expiry and supersession during cleanup. A new controller must not reuse the
  resource until an independent watchdog proves teardown within the configured deadline; deadline
  failure remains quarantined and visible to the operator.
- **LIFE-02 Safe rollback.** Simulate disabling the new execution lane. No fallback executes PR
  code without containment; stale/incomplete results lose eligibility. Static/manual review
  remains available. Re-enabling requires the approved pinned runtime and passing contract.
- **LIFE-03 Retention and access.** Missing numeric retention/access policy must block capture or
  publication. Verify raw diagnostics are disabled by default, allowed readers cannot expand
  access, and synthetic audit/evidence/quarantine/storage items expire under their configured
  limits. Failed deletion remains observable for the operator. Public summaries contain no
  private content that would depend on a later successful recall.

## Acceptance decision

Runtime selection must precede execution of this plan. Approval of the design alone does not run
it. A future implementation is acceptable only when every mandatory case has trusted real-boundary
evidence for its final commit, with no failed, blocked, inconclusive, or not-run mandatory cases.
Unit mocks and argument-shape checks are supplementary. Review any exception explicitly instead
of relabeling it as passed.

Record the exact environment and limits actually tested. Do not extrapolate from one runner,
kernel, runtime, CLI, or toolchain to another without renewed evidence. A successful offline suite
supports only the tested containment contract; live credentials, deployed behavior, and historical
exploitability remain outside its claim.
