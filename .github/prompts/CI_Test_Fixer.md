---
mode: 'agent'
description: >-
  Pick a small batch of unchecked CI/test issues from notes/, fix them, add validated
  outages entries (only for fixes in this PR), update notes/, and open a PR.
tools: ['github', 'playwright']
---

**Goal**
Fix a small, independent batch of remaining CI/test failures documented under `notes/`.
Document each fix with a conformant `outages/` entry (only if the fix lands in the same PR),
update the checkboxes in `notes/`, and open a focused PR.
While working, clean up the related `nodes/` entries by pruning stale diagnostics, removing
dead links, and adding clarifying breadcrumbs so future investigators inherit better context
than before.

**Plan**
1) Parse:
   - #file:notes/ci-test-fixes-action-plan.md
   - #file:notes/ci-test-failures-remaining-work.md
   Enumerate all **unchecked** checkboxes and note any missing investigative details that
   make reproduction difficult (e.g., absent log snippets, unknown owners, fuzzy repro steps).

1a) **CRITICAL: Understand the Real Use Case First** (avoid XY problem)
   
   Before attempting to fix any test, especially integration tests, **always read the relevant 
   documentation to understand what the test is actually trying to validate**. Don't get stuck 
   fixing implementation details without understanding the user scenario.
   
   **Key Resources:**
   - #file:docs/raspi_cluster_setup.md - The REAL use case for k3s integration tests
   - Test file comments and fixture data - Often explain the scenario
   - Related scripts under `scripts/` - The actual code being tested
   
   **Example: K3s Integration Tests (discover_flow.bats Tests 6-8)**
   
   ❌ **Wrong approach (XY problem)**: "These tests timeout during k3s installation. Let me add 
   `SUGARKUBE_SKIP_K3S_INSTALL` to skip the curl command."
   
   ✅ **Right approach (understand use case)**: 
   1. Read docs/raspi_cluster_setup.md to understand the Pi cluster workflow
   2. Realize tests validate **mDNS-based discovery and join decision logic**, not k3s installation
   3. Understand the 3 scenarios:
      - Test 6: Node discovers existing server via mDNS → joins it (phase=install_join)
      - Test 7: No servers found + election logic → bootstrap as winner (phase=install_single)
      - Test 8: No servers found + lost election → wait as follower
   4. Recognize the actual fix: stub the k3s installation (like other tools), test only the 
      decision-making logic
   5. Follow the pattern: use `SUGARKUBE_K3S_INSTALL_SCRIPT` env var (like 
      `SUGARKUBE_API_READY_CHECK_BIN`, `SUGARKUBE_CONFIGURE_AVAHI_BIN`)
   
   **The Pattern:**
   - Real user scenario: Raspberry Pis boot, share LAN, discover each other via mDNS, form k3s cluster
   - What test validates: Discovery logic, join decisions, election outcomes
   - What test should NOT validate: Actual k3s installation (that's an external dependency)
   - Correct test approach: Stub external dependencies, verify decision logic
   
   **When working on ANY integration test:**
   1. Find and read the relevant docs/ file(s) that explain the user workflow
   2. Identify what behavior the test is ACTUALLY validating
   3. Distinguish between "the logic being tested" vs "external dependencies"
   4. Stub external dependencies following existing patterns in the codebase
   5. Focus test on validating the decision-making logic
   
   **Anti-patterns to avoid:**
   - Adding skip flags without understanding what should be tested
   - Trying to mock entire subsystems (k3s, systemd) in unit tests
   - Missing the forest for the trees (fixing timeouts without understanding scenarios)

2) **Prioritize tangible progress**: Select 1–2 items that can be implemented together with minimal risk. 
   **IMPORTANT**: Even if all checkboxes are complete, look for at least one small improvement that moves 
   the needle toward 0 CI failures. Examples:
   - Enable a skipped test by installing missing dependencies
   - Fix environment configuration issues
   - Update stale notes/documentation that could confuse future work
   - Implement timeout overrides for hanging tests
   
   If no items are fully fixable, choose a **partial progress strategy** from the playbook below.
   
   - **Select 1–2 unchecked items maximum** that can be completed together.
   - **Time estimation guidance**: When estimating task complexity, lean toward smaller time
     estimates (minutes to ~1 hour for agentic workflows) rather than longer human-scale
     estimates. Most test fixes that appear to require "2-4 hours" for humans can typically
     be completed in 15-30 minutes with focused agentic iteration.
   
   **Partial Progress Playbook** (use when no items are fully fixable in one session):
   
   a) **Investigation & Documentation** (15-30 min)
      - Run failing test with verbose logging and capture full output
      - Trace execution path to identify exact failure point
      - Document findings in notes/ with:
        - Exact failure location (file:line)
        - Root cause hypothesis
        - Repro steps that work
        - Next implementation steps
      - Update test skip directive with better context
      - Create partial outage entry documenting investigation (mark as "partial" in description)
   
   b) **Test-Only Refactoring** (20-40 min)
      - Extract complex test setup into reusable helper functions
      - Split large test file into focused modules (e.g., `tests/bats/mdns_helpers.sh`)
      - Create shared fixtures that multiple tests can use
      - Improve test naming/organization for clarity
      - Benefits: Makes future fixes easier, no production code risk
   
   c) **Script Modularization** (30-60 min)
      - Extract monolithic script functions into separate files
      - Move reusable logic into `scripts/lib/` modules
      - Create clear interfaces between modules
      - Add unit tests for extracted functions
      - Benefits: Enables incremental testing, reduces scope of future changes
      - Example: Extract `wait_for_avahi_dbus()` from 600-line script into `scripts/lib/dbus_wait.sh`
   
   d) **Environment Configuration Externalization** (15-25 min)
      - Move hardcoded timeouts/retries to environment variables
      - Document new variables in script headers and notes/
      - Update tests to use faster timeouts via env vars
      - Benefits: Makes tests faster, more configurable, easier to debug
      - Example: Replace `timeout_ms=15000` with `timeout_ms="${MDNS_TIMEOUT_MS:-15000}"`
   
   e) **Stub Infrastructure Improvement** (20-35 min)
      - Create reusable stub library in `tests/bats/lib/stubs/`
      - Standardize stub patterns across tests (e.g., trap handlers, sleep loops)
      - Document stub usage patterns in test README
      - Benefits: Makes adding new stubs faster, reduces copy-paste errors
   
   f) **Incremental Implementation** (30-60 min)
      - Implement 50-70% of required logic with TODOs for remainder
      - Update test to reflect partial progress (may still skip but with better reason)
      - Commit with clear "partial fix" message
      - Document remaining work in notes/
      - Benefits: Future sessions can build on working foundation
      - Example: Implement retry logic but leave error handling for next PR
   
   **When to use partial progress**:
   - Test requires >60 min to fully fix
   - Multiple interrelated issues found during investigation
   - Complex integration scenario needs architectural changes
   - Root cause unclear and needs experimentation
   
   **Always for partial progress**:
   - Update notes/ with detailed findings and next steps
   - Mark checkboxes as "⚙️ Partial" instead of "✅ Complete"
   - Create outage entry with `"resolution": "Partial: <what was done> | Remaining: <next steps>"`
   - Keep test skip directive but improve context in comment

3) Implement:
   - Make the minimal code/test changes needed to resolve each selected item.
   - Identify test commands from the Makefile and `.github/workflows/*.yml`. Run locally the
     same suites CI runs (BATS, Playwright E2E, QEMU smoke, etc.) and iterate until green for
     the affected areas.
   - As you touch a `nodes/` entry, remove obsolete context and enrich the record with the
     freshest evidence (log excerpts, repro commands, owners) so unresolved failures have a
     clearer investigative trail.
   
   **Scope Control & Pivot Signals**:
   
   If during implementation you encounter any of these signals, **pivot to partial progress**
   instead of abandoning the work:
   
   - ⚠️ **Investigation reveals complexity**: Initial 30-min estimate now looks like 2+ hours
     → Switch to strategy (a) "Investigation & Documentation"
   
   - ⚠️ **Multiple interdependent issues**: Fixing A requires fixing B which requires C
     → Choose strategy (c) "Script Modularization" to separate concerns
   
   - ⚠️ **Test infrastructure gaps**: Missing reusable stubs, helpers, or fixtures
     → Switch to strategy (b) "Test-Only Refactoring" or (e) "Stub Infrastructure"
   
   - ⚠️ **Unclear root cause**: Test fails for unknown reason after 30 min investigation
     → Use strategy (a) to document what you've learned + hypotheses
   
   - ⚠️ **Hardcoded values blocking testing**: Script has fixed timeouts/retries
     → Apply strategy (d) "Environment Configuration" to make testable
   
   - ⚠️ **Clear path forward but time-constrained**: Know what to do but >60 min to complete
     → Use strategy (f) "Incremental Implementation" to make progress
   
   **Progress over perfection**: A well-documented partial fix with actionable next steps is
   more valuable than no PR at all. Future agents (or the same agent in next session) can
   build on partial work more effectively than starting from scratch.

**Definition of Done**

For **complete fixes**:
- `scripts/ci_commands.sh` passes locally end-to-end.
- All `outages/*.json` added in this PR pass `scripts/validate_outages.py`.
- PR body uses the provided template verbatim and quotes the exact `notes/` checkboxes checked.
- Total diff ≤ ~300 LOC excluding lockfiles/snapshots.
- `notes/` checkboxes marked with ✅ for completed items.

For **partial progress** (when using playbook strategies):
- Document investigation findings or refactoring rationale in notes/
- Create outage entry with "Partial: <accomplished> | Remaining: <next steps>" resolution
- Update test skip directives with improved context from investigation
- Mark `notes/` checkboxes as "⚙️ Partial - <strategy used>" with link to detailed findings
- Total diff ≤ ~300 LOC excluding lockfiles/snapshots
- `scripts/ci_commands.sh` passes (tests may still skip but with better documentation)

For **all PRs** (complete or partial):
- `notes/` and `nodes/` reflect the freshest findings
- Open items carry actionable next steps
- Unsolved failures capture the latest hypotheses with evidence

4) Outages:
   - For each fixed failure, create `outages/<yyyy-mm-dd>-<short-slug>.json` describing the
     failure and resolution. Conform **exactly** to `#file:outages/schema.json`.
   - Validate each JSON against the schema before committing (use a JSON Schema validator).
   - Only add outages entries for fixes included in this PR.
   
   **For partial progress PRs**:
   - Create outage entry documenting what was investigated/refactored/implemented
   - Use resolution format: `"Partial: <what was accomplished>. Remaining: <specific next steps with estimates>."`
   - Example partial resolution:
     ```json
     "resolution": "Partial: Investigated Test 34 timeout issue. Root cause identified as mdns_absence_gate default timeout (15s) exceeding test timeout (30s). Attempted timeout overrides but additional stubs needed. Remaining: Add environment variables MDNS_ABSENCE_TIMEOUT_MS=2000, verify restart_avahi_daemon_service stub, test with verbose logging (est. 30-45 min)."
     ```
   - Include investigation findings in outage references (e.g., log excerpts, stack traces)

   **Outages schema validation (required)**
   - `python3 scripts/validate_outages.py outages/2025-*.json`
   - `jq -e . outages/*.json`

5) Notes:
   - Check off completed items in `notes/ci-test-failures-remaining-work.md` (and
     `notes/ci-test-fixes-action-plan.md` if applicable).
   - For new bugs discovered, append new unchecked boxes with brief details and repro pointers.
   
   **For partial progress**:
   - Mark items as `⚙️ Partial - <strategy>` instead of `✅ Complete`
   - Add detailed subsection explaining what was accomplished and what remains
   - Include specific next steps with time estimates
   - Example:
     ```markdown
     - ⚙️ Partial - Investigation & Documentation: Test 34 mdns absence gate
       - ✅ Identified root cause: timeout configuration (see outages/2025-11-06-test34-investigation.json)
       - ✅ Attempted fix: timeout overrides (insufficient)
       - 🔲 Remaining: Add restart_avahi_daemon_service stub (est. 15-20 min)
       - 🔲 Remaining: Verify absence gate completes with reduced timeouts (est. 10-15 min)
     ```

6) PR:
   - Branch: `ci/fix/<area>-<yyyymmdd>`
   - Labels: `ci`, `tests`, `outages`
   - Title: `ci: fix <short summary> (+ outages)`
   - Body sections: **Summary**, **Outages entries** (paths), **Notes updated** (quote exact
     checkboxes), **Verification** (commands + results), **Follow‑ups** (remaining unchecked
     boxes).

**Do not change** (unless required for the fix):
- `outages/schema.json` - never change
- Logging levels or semantics - preserve unless test specifically needs it
- Unrelated Playwright snapshots - only update if test requires
- Production code APIs - keep backwards compatible
- Code unrelated to failing tests - stay focused

**Acceptable to change** (when it helps the fix):
- Test infrastructure (stubs, fixtures, helpers)
- Script modularization (extracting functions to lib/)
- Environment variable configuration
- Test-only refactoring
- Documentation and comments

If any chosen item balloons in scope, **drop it from this PR**, restore/append an unchecked
box in `notes/…` with repro details and a brief scope estimate.

**Time Estimation Guidelines for Agentic Workflows**:
- Simple test stub additions: ~5-10 minutes
- Test fixture corrections: ~10-15 minutes  
- Logic bugs requiring code changes: ~15-30 minutes
- Complex integration scenarios: ~30-60 minutes
- Lean toward smaller estimates; most fixes complete faster than human-scale time estimates suggest.

Reproduce suspected flakes **3× locally** and apply the **least-invasive** stabilization
(timeouts/retries/backoff) only. Document evidence under **Stabilizations** in the PR body
(logs or notes).

Upload relevant test logs as CI artifacts and summarize key lines (≤5 bullets) in the PR body.

**Agent must not open a PR unless** (1) `scripts/ci_commands.sh` passes locally; (2) all
added `outages/*.json` pass `scripts/validate_outages.py`; (3) the PR body uses the provided
template and quotes the exact `notes/` checkboxes.

**Success Patterns from Past PRs** (apply these learnings):

1. **Documentation-first investigation pays off**
   - Spending 30 min documenting findings > 2 hours trial-and-error
   - Future agents can build on documented investigations
   - Example: Test 34 investigation documented timeout issue, saving next agent 1+ hour
   
2. **Environment configuration is low-hanging fruit**
   - Adding env vars for timeouts/retries: 15-25 min typically
   - Makes tests faster and more debuggable
   - Zero production code risk
   
3. **Stub patterns should be reusable**
   - Don't copy-paste stubs across tests
   - Extract to `tests/bats/lib/stubs/` if used >2 times
   - Use trap handlers for interruptible background processes
   
4. **Modular scripts are easier to test**
   - 600-line scripts are hard to test in isolation
   - Extracting functions to `scripts/lib/` enables unit testing
   - 30-60 min investment saves hours in future fixes
   
5. **Timeout issues often have multiple causes**
   - Don't assume first fix will work
   - Test with verbose logging to see actual flow
   - Document what you tried even if it didn't work

6. **Notes synchronization prevents confusion**
   - Update test counts across all notes/ files
   - Mark completed tests as ✅ everywhere
   - Remove stale checkboxes to reduce noise

**PR Body Template (use verbatim)**
~~~md
## Summary
- Fixed: <bullet list>
- Rationale: <1–2 sentences per item>

## Verification (must match CI)
Commands run locally:
```bash
bash scripts/ci_commands.sh
```
Results:

BATS: ✅ pass

E2E/Playwright: ✅ pass

QEMU smoke: ✅ pass

CI runs:

Before: <link>

After: <link>

Outages entries (added in this PR)
outages/<yyyy-mm-dd>-<short-slug>.json

Schema checks:

```bash
jq -e . outages/<yyyy-mm-dd>-*.json
python3 scripts/validate_outages.py outages/<yyyy-mm-dd>-*.json
```

Notes updated
Checked off:

<quoted line from notes/ci-test-failures-remaining-work.md>

<quoted line from notes/ci-test-fixes-action-plan.md>

Stabilizations (if any)
Test: <name> — Change: <minimal tweak> — Why: <flake evidence>

Follow-ups
Remaining unchecked boxes (verbatim from notes/)

```python
<copy remaining unchecked boxes>
```
~~~

**Constraints**
- Keep scope tight (≈1–3 items; ≤ ~300 changed lines excluding generated/snapshot files).
- Preserve logging semantics unless a specific test requires changes.
- Do not modify `outages/schema.json`.
- Always leave `notes/` and `nodes/` better than found: clarify owners, surface fresh log
  links, and record next investigative steps for anything still failing.

**Refactoring is acceptable when**:
- It's test-only (no production code impact)
- It extracts reusable components that help multiple tests
- It makes future fixes significantly easier (e.g., modularizing 600-line script)
- It's scoped to affected area only (don't refactor entire codebase)
- Total diff stays within 300 LOC limit

**Refactoring is NOT acceptable when**:
- It changes public APIs or contracts
- It touches production code unrelated to the failing test
- It restructures architecture without clear test-fixing benefit
- It exceeds 300 LOC limit (split into separate refactoring PR instead)
