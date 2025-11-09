# 2025-11-09: Test 7 "discover flow elects winner after self-check failure" CI failures (4-bug cascade fix)

## Background

Test 7 in `tests/bats/discover_flow.bats` was consistently failing in CI under kcov code coverage instrumentation, despite the test scenario being correctly designed. The test validates the bootstrap election resilience scenario where a node becomes the first server in a k3s cluster after handling a transient mDNS publish failure.

The test is designed to validate decision-making logic for this real-world use case (per `docs/raspi_cluster_setup.md`):
1. Node discovers no existing k3s servers via mDNS
2. Node runs bootstrap election to decide who initializes cluster  
3. Election winner attempts to publish mDNS advertisement
4. **If initial publish fails** (transient multicast issue), node re-runs election
5. Winner proceeds with k3s bootstrap using `--cluster-init` (embedded etcd)

The failures manifested as the test producing no output at all and never executing the k3s-discover.sh script, making it appear as if the test infrastructure was completely broken. This issue required careful forensic analysis across multiple commits to identify a cascade of four separate test infrastructure bugs.

## Root Cause

The root cause was a **cascade of four critical test infrastructure bugs** that prevented the test from executing at all:

1. **Wrong environment variable name** (line 696): Used `MDNS_ABSENCE_GATE=0` instead of `SUGARKUBE_MDNS_ABSENCE_GATE=0`, causing the script to run the real absence gate check which queried the actual Avahi daemon and hung indefinitely

2. **Broken timeout stub** (lines 604-609): Stub implementation returned `exit 0` immediately without executing the command, preventing k3s-discover.sh from ever running

3. **Static mdns_selfcheck stub** (line 656-673): Stub always exited with status 94 (failure) for both bootstrap and server roles, when it should fail for bootstrap (to trigger election) but succeed for server (to allow completion)

4. **Wrong test expectations** (lines 732-733): Expected `txt=role=bootstrap` and `txt=phase=bootstrap` after election, when the actual behavior is to install as server and publish server advertisement

These bugs compounded each other - even fixing bugs 1-2 wouldn't reveal bug 3, and fixing bugs 1-3 wouldn't reveal bug 4. The test needed all four fixes to pass.

### Why This Was Hard to Diagnose

1. **No output at all**: The broken timeout stub meant the script never ran, producing zero output and making it seem like the test infrastructure was completely broken

2. **Multiple layers of failure**: Each bug masked the next bug in the sequence, requiring iterative fixes to peel back the layers

3. **Environment variable subtlety**: The variable name difference (missing `SUGARKUBE_` prefix) was easy to miss, especially when cross-referencing with other tests

4. **Test expectations mismatch**: The test comments and assertions didn't match the actual script behavior (server role vs bootstrap role after election)

5. **Partial prior investigation**: A previous investigation (`2025-11-08-discover-flow-test7-partial-investigation.md`) had made 85% progress but focused on output capture issues rather than the test infrastructure bugs

## Detailed Explanation

### The Investigation Journey

This issue built upon a previous partial investigation that had gotten 85% of the way to a solution but stalled on the wrong hypothesis:

**Prior Work (2025-11-08)**: Partial investigation identified output capture issues
- Investigation: `outages/2025-11-08-discover-flow-test7-partial-investigation.json`
- Progress: Removed skip directive, added use case documentation, fixed some environment variables
- Status: Test completed but captured no output (85% complete)
- Hypothesis: BATS output capture was broken or script logged to wrong stream
- Reality: This was correct in identifying output issues but missed that script wasn't running at all

**Current Investigation (2025-11-09)**: Root cause forensic analysis
- Started fresh with assumption that test infrastructure was broken
- Systematically debugged why script wasn't producing output
- Discovered cascade of four separate bugs through iterative fixing

### The Debugging Iterations

**Iteration 1 (commit 0ac0957)**: Add debug step to CI workflow
- Added dedicated CI step to capture Test 7 output before kcov run
- Goal: Understand if issue was BATS, kcov, or the test itself
- Result: Would have shown no output, but this revealed nothing due to bug #2

**Iteration 2 (commit 6b9424a)**: Fix environment variable name
- Changed `MDNS_ABSENCE_GATE=0` to `SUGARKUBE_MDNS_ABSENCE_GATE=0`
- Root cause: Script reads `SUGARKUBE_MDNS_ABSENCE_GATE` (k3s-discover.sh:166)
- Impact: Removed the hang caused by running real absence gate check
- Result: Test still produced no output (bug #2 still present)

**Iteration 3 (commit a426c71)**: Fix timeout stub and mdns_selfcheck stub
- Fixed timeout stub from `exit 0` to `shift; exec "$@"`
- Created smart mdns_selfcheck stub that checks `SUGARKUBE_EXPECTED_ROLE`
- Root cause: timeout stub prevented any command execution
- Impact: Script finally ran and produced output
- Result: Test still failed with wrong exit status (bug #4 still present)

**Iteration 4 (commit a426c71)**: Fix test expectations
- Changed expectations from `txt=role=bootstrap` to `txt=role=server`
- Changed expectations from `txt=phase=bootstrap` to `txt=phase=server`
- Root cause: After election, node installs as server (not bootstrap)
- Impact: Test assertions now matched actual script behavior
- Result: ✅ Test passed! All 4 bugs fixed

**Iteration 5 (commit c533002)**: Document outage
- Created JSON outage entry documenting all 4 root causes
- Validated with `validate_outages.py`
- Result: Proper documentation for future reference

**Iteration 6 (commit 329e2a8)**: Fix documentation errors
- Fixed "three" to "four" bugs in rootCause field
- Corrected line numbers (696 instead of 679, 732-733 instead of 746-747)
- Result: Accurate documentation with correct details

### Related Issues and Context

Several related outage entries document parts of this journey:

1. **2025-11-08-discover-flow-test7-partial-investigation.json**: 85% complete investigation that got output capture hypothesis but missed infrastructure bugs

2. **2025-11-08-k3s-integration-tests-investigation.json**: Broader investigation of Tests 6-8, documented complexity of k3s integration testing

3. **2025-11-08-k3s-integration-tests-stub-infrastructure.json**: Documents stub infrastructure for k3s integration tests that Test 7 uses

While the prior investigation made significant progress (removed skip directive, added documentation, fixed some environment variables), it focused on BATS output capture rather than the fundamental test infrastructure bugs. This is a good example of how getting 85% of the way there doesn't mean you're 85% of the time away from completion - the last 15% can require completely different approach.

## Resolution

### The Fixes

**Fix 1: Environment variable name (line 696)**
```bash
# Before: Wrong variable name, absence gate runs anyway
MDNS_ABSENCE_GATE=0

# After: Correct variable name read by script
SUGARKUBE_MDNS_ABSENCE_GATE=0
```

**Fix 2: Timeout stub (lines 604-609)**
```bash
# Before: Never executes command
stub_command timeout <<'EOS'
#!/usr/bin/env bash
exit 0
EOS

# After: Passes through to actual command
stub_command timeout <<'EOS'
#!/usr/bin/env bash
shift  # Remove timeout value
exec "$@"
EOS
```

**Fix 3: Smart mdns_selfcheck stub (lines 661-673)**
```bash
# Before: Always failed with exit 94
mdns_stub="$(create_mdns_stub 94)"

# After: Smart stub that checks role
mdns_stub="${BATS_TEST_TMPDIR}/mdns-selfcheck-smart.sh"
cat <<'EOS' > "${mdns_stub}"
#!/usr/bin/env bash
# Fail for bootstrap role (triggers election)
if [ "${SUGARKUBE_EXPECTED_ROLE:-}" = "bootstrap" ]; then
  exit 94
fi
# Succeed for server role (allows completion)
echo "host=${SUGARKUBE_EXPECTED_HOST:-stub.local} attempts=1 ms_elapsed=5"
exit 0
EOS
chmod +x "${mdns_stub}"
```

**Fix 4: Test expectations (lines 732-733)**
```bash
# Before: Expected bootstrap role/phase
[[ "$output" =~ txt=role=bootstrap ]]
[[ "$output" =~ txt=phase=bootstrap ]]

# After: Expect server role/phase (actual behavior)
[[ "$output" =~ txt=role=server ]]
[[ "$output" =~ txt=phase=server ]]
```

### Rationale

Each fix addresses a specific layer of the problem:

1. **Environment variable**: The script explicitly checks for `SUGARKUBE_MDNS_ABSENCE_GATE` (line 166), not `MDNS_ABSENCE_GATE`. Without the correct variable name, the absence gate runs and queries real Avahi, causing indefinite hangs.

2. **Timeout stub**: The stub must actually execute the command, not just return success. The pattern `shift; exec "$@"` removes the timeout value from arguments and executes the remaining command.

3. **Smart mdns_selfcheck stub**: The test scenario requires bootstrap self-check to fail (triggering re-election) but server self-check to succeed (completing installation). A static stub can't model this - we need role-aware behavior.

4. **Test expectations**: After election, `install_server_single()` is called which publishes a server advertisement, not a bootstrap advertisement. The test assertions must match actual script behavior.

### Additional Improvements (Side Benefits)

As part of this debugging journey, several documentation improvements were made:

1. **Use case documentation**: Added comprehensive comments to Test 7 explaining the real-world scenario being validated (per `docs/raspi_cluster_setup.md`)

2. **Removed debug CI step**: Cleaned up the temporary debug step added during investigation (commit 0ac0957 → removed in a426c71)

3. **Outage documentation**: Created detailed JSON and markdown documentation for future reference

## Verification Steps

1. Run Test 7 locally:
   ```bash
   export BATS_CWD="${PWD}" BATS_LIB_PATH="${PWD}/tests/bats"
   bats -f "discover flow elects winner after self-check failure" tests/bats/discover_flow.bats
   # Should show: ok 1 discover flow elects winner after self-check failure
   ```

2. Run full BATS suite:
   ```bash
   export BATS_CWD="${PWD}" BATS_LIB_PATH="${PWD}/tests/bats"
   bats --recursive tests/bats
   # Should show: 39/42 passing (92.8% pass rate)
   # Test 7: ok 7 discover flow elects winner after self-check failure
   ```

3. Run in CI with kcov:
   ```bash
   # CI runs: kcov --include-path=... bats --recursive tests/bats
   # Should show: ok 7 discover flow elects winner after self-check failure
   # No timeout or hang issues
   ```

4. Verify test validates correct scenario:
   ```bash
   # Check that test asserts on election logging
   grep -A 5 "event=bootstrap_selfcheck_election" tests/bats/discover_flow.bats
   # Should show assertions for outcome=winner and phase=install_single
   ```

## Future Action Items

### 1. Audit Other Tests for Similar Patterns

Review remaining discover_flow.bats tests for similar issues:

- **Test 6**: Currently skipped, may have similar stub issues
- **Test 8**: Currently skipped, may have similar stub issues  
- **Other tests using timeout stub**: Verify all tests that stub timeout do so correctly

### 2. Improve Test Infrastructure

Enhance test stub infrastructure to prevent similar issues:

- **Create reusable stub library**: Extract common stub patterns to `tests/bats/lib/stubs/`
- **Add stub validation**: Create helper that verifies stubs are executable and work correctly
- **Document stub patterns**: Add README explaining timeout stub, mdns stub, and other patterns

### 3. Environment Variable Naming Convention

Establish clear convention for environment variables:

- **Audit all tests**: Find tests that may use wrong variable names (missing SUGARKUBE_ prefix)
- **Document variable mapping**: Create reference showing shell variable → environment variable mapping
- **Add linting**: Consider adding check that validates environment variable names in tests

### 4. Test Expectation Validation

Improve test assertion accuracy:

- **Review test comments**: Ensure test descriptions match actual assertions
- **Validate expected output**: Run tests with real output to verify expectations are correct
- **Document behavior**: Add inline comments explaining why specific output is expected

### 5. Progressive Disclosure Testing

Develop better debugging workflow for cascading failures:

- **Add incremental test modes**: Create intermediate tests that validate each layer separately
- **Improve error messages**: Make test failures more informative about which layer failed
- **Document debugging approach**: Create guide for investigating multi-bug test failures

## References

- [k3s-discover.sh bootstrap election logic](scripts/k3s-discover.sh:3721-3752)
- [Raspberry Pi cluster setup guide](docs/raspi_cluster_setup.md)
- Related outages:
  - `outages/2025-11-08-discover-flow-test7-partial-investigation.json` (85% progress, wrong hypothesis)
  - `outages/2025-11-08-discover-flow-test7-partial-investigation.md` (detailed partial investigation)
  - `outages/2025-11-08-k3s-integration-tests-investigation.json` (broader context)
  - `outages/2025-11-08-k3s-integration-tests-stub-infrastructure.json` (stub infrastructure)
  - `outages/2025-11-09-test7-discover-flow-election-fix.json` (this fix - JSON metadata)
- Pull request: Branch `copilot/fix-ci-test-failures`
- Commits:
  - `0ac0957`: ci: add debug step for Test 7 output capture investigation
  - `6b9424a`: fix(test): correct environment variable name for Test 7
  - `a426c71`: fix(test): resolve Test 7 failures - fix timeout stub and mdns self-check
  - `c533002`: docs: add outage documentation for Test 7 fix
  - `329e2a8`: fix: correct line numbers and bug count in outage documentation
- CI workflow: `.github/workflows/ci.yml:57-71`
- Test file: `tests/bats/discover_flow.bats:595-751`
- Script: `scripts/k3s-discover.sh:3640-3760`
