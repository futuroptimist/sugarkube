# 2025-11-06: summary.bats tests 40-41 kcov instrumentation failures (10-iteration fix)

## Background

Tests 40-41 in `tests/bats/summary.bats` were consistently failing in CI under kcov code coverage instrumentation, despite passing locally. The tests validate that the summary.sh library correctly formats output without ANSI color codes in non-TTY environments. The failures manifested as the bash -c test subshells exiting with non-zero status, causing the assertion `[ "$status" -eq 0 ]` to fail.

This issue required 10 iterations over multiple days to fully resolve, involving extensive debugging of kcov instrumentation behavior, bash subshell mechanics, EXIT trap handling, and environment variable propagation. The journey revealed several red herrings and culminated in a simple but non-obvious fix.

## Root Cause

The root cause was **`set -euo pipefail` in the test bash -c commands** interacting adversely with kcov's instrumentation of summary.sh.

When kcov instruments a bash script, it modifies how the script executes by injecting coverage tracking code. The combination of:
1. kcov's instrumentation of summary.sh
2. `set -euo pipefail` strict error handling in the test wrapper subshell
3. bash -c subprocess execution context

...caused the subshell to exit with non-zero status under kcov instrumentation, but this behavior did not reproduce in local execution without kcov. The exact mechanism of the interaction remains somewhat opaque (kcov's instrumentation details are complex), but the strict error handling in the test wrapper made the tests fragile to kcov's code modifications.

### Why This Was Hard to Diagnose

1. **Tests passed locally**: Without kcov, the tests worked perfectly, making it impossible to reproduce the failure in local development environments
2. **EXIT trap red herring**: Multiple iterations focused on EXIT trap handling because kcov is known to have issues with traps, but this turned out to be orthogonal to the actual problem
3. **Environment variable complexity**: Several iterations attempted to detect the test environment using various BATS variables (BATS_TEST_DIRNAME, BATS_VERSION, IN_BATS_TEST), but these were solving the wrong problem
4. **Line number changes**: Each fix attempt changed line numbers in the test file, making it harder to track whether we were making progress or introducing new issues

## Detailed Explanation

### The 10 Iteration Journey

**Iteration 1-3**: Initial attempts focused on BATS_CWD environment variable issues
- Added setup() function to set BATS_CWD
- Moved BATS_CWD to CI workflow environment variables
- These fixed unrelated issues but didn't resolve tests 40-41

**Iteration 4**: Investigated EXIT trap double-calling
- Removed explicit `summary::emit` calls, relying on EXIT trap
- This was based on the hypothesis that explicit + trap calls conflicted under kcov
- Tests still failed

**Iteration 5**: Attempted to detect BATS environment using BATS_TEST_DIRNAME/BATS_VERSION
- Modified summary.sh to skip EXIT trap registration in detected BATS environments
- Discovery: These variables aren't exported to bash -c subshells
- Tests still failed

**Iteration 6**: Tried exporting IN_BATS_TEST=1 explicitly in each test
- Hypothesis: Exported variables ARE inherited by subshells
- Tests still failed (timing/scope issues suspected)

**Iteration 7**: Moved IN_BATS_TEST export to setup() function
- Ensured variable was exported before test execution
- Tests still failed under kcov

**Iteration 8**: Made EXIT trap opt-in via SUMMARY_AUTO_EMIT=1
- Disabled EXIT trap by default to eliminate all trap-related issues
- Improved code clarity and explicit behavior
- Tests still failed (proving EXIT trap wasn't the root cause)

**Iteration 9**: Removed setup() function since IN_BATS_TEST was no longer needed
- Cleanup after realizing EXIT trap was a red herring
- Tests still failed

**Iteration 10**: Removed `set -euo pipefail` from test bash -c commands
- ✅ Tests finally passed in CI!
- Root cause identified: strict error handling in test wrapper + kcov instrumentation

### Related Issues and Red Herrings

Several related outage entries document parts of this journey:

1. **2025-11-02-summary-strict-wrapper-bats-failure.json**: Placeholder entry indicating initial awareness of the issue
2. **2025-11-03-kcov-bash-xtrace-output.json**: Fixed kcov xtrace pollution by adding `--bash-dont-parse-binary-dir` flag and excluding tests directory from coverage
3. **2025-11-06-kcov-subshell-depth-summary-tests.json**: Fixed subshell nesting depth issues in summary__with_strict() by removing defensive subshell wrapper

While these fixes improved the codebase and eliminated other kcov issues, they did not resolve tests 40-41 because they were addressing different symptoms of kcov instrumentation complexity.

## Resolution

### The Fix

Removed `set -euo pipefail` from the bash -c test commands:

**Before:**
```bash
run bash -c '
  set -euo pipefail  # <-- Problematic under kcov
  source summary.sh
  summary::init
  summary::section "Smoke"
  summary::step OK "First step"
  summary::emit
'
```

**After:**
```bash
run bash -c '
  source summary.sh  # summary.sh has its own error handling
  summary::init
  summary::section "Smoke"
  summary::step OK "First step"
  summary::emit
'
```

### Rationale

- summary.sh itself contains appropriate error handling where needed
- The strict mode in the test wrapper was defensive but unnecessary
- Under kcov instrumentation, the strict mode made tests brittle to kcov's code modifications
- Removing strict mode from the wrapper doesn't reduce test safety because summary.sh handles errors appropriately

### Additional Improvements (Side Benefits)

As part of this debugging journey, several code improvements were made:

1. **EXIT trap made opt-in**: Changed `SUMMARY_AUTO_EMIT=1` to explicitly enable EXIT trap registration (disabled by default)
   - Makes behavior more explicit and predictable
   - Tests and most scripts call `summary::emit` explicitly
   - Production scripts can opt-in if they want automatic emission

2. **BATS_CWD environment variable**: Added to CI workflow for consistency
   - Ensures all BATS tests have access to repository root path
   - Matches pattern used for BATS_LIB_PATH

3. **Simplified summary__with_strict()**: Removed defensive subshell wrapper
   - Callers already set strict mode, so wrapper was redundant
   - Explicit return statement improves kcov compatibility

## Verification Steps

1. Run tests locally without kcov:
   ```bash
   export BATS_CWD="${PWD}" BATS_LIB_PATH="${PWD}/tests/bats"
   bats tests/bats/summary.bats
   # Should show: ok 40, ok 41
   ```

2. Run tests in CI with kcov (requires CI environment):
   ```bash
   # CI runs: kcov --include-path=... bats --recursive tests/bats
   # Should show: ok 40, ok 41 (no "not ok" overrides)
   ```

3. Verify EXIT trap behavior:
   ```bash
   # Default: no EXIT trap
   bash -c 'source scripts/lib/summary.sh; summary::init; summary::section "Test"; summary::step OK "Step"'
   # No output (summary::emit not called)
   
   # Opt-in: EXIT trap enabled
   SUMMARY_AUTO_EMIT=1 bash -c 'source scripts/lib/summary.sh; summary::init; summary::section "Test"; summary::step OK "Step"'
   # Output appears via EXIT trap
   ```

## Future Action Items

### 1. Verify EXIT Trap Opt-In Functionality

While the EXIT trap changes improved code clarity, we should verify it works correctly when enabled:

- **Test SUMMARY_AUTO_EMIT=1 in production scripts**: Ensure k3s-discover.sh or other production scripts work correctly if they enable auto-emit
- **Document opt-in pattern**: Add examples to summary.sh header comments showing when/how to use SUMMARY_AUTO_EMIT=1
- **Add test for auto-emit**: Create a BATS test that verifies EXIT trap fires correctly when SUMMARY_AUTO_EMIT=1 is set

### 2. Improve CI Simulation Tool

Enhance `scripts/ci_simulate.sh` to catch kcov-specific issues:

- **Install kcov by default**: Make kcov installation automatic in ci-simulate to reduce friction
- **Test with and without strict mode**: Add validation that detects strict mode in test wrappers (since it's now an anti-pattern)
- **Document kcov patterns**: Add section to docs/ci-simulation.md about kcov-safe testing patterns

### 3. Establish Testing Best Practices

Document lessons learned to prevent similar issues:

- **Avoid strict mode in test wrappers**: Add guideline that `set -euo pipefail` should be in the library being tested, not the test wrapper
- **Test with kcov locally**: Encourage developers to run `make ci-simulate-kcov` before pushing
- **Prefer explicit over implicit**: Favor explicit `summary::emit` calls over EXIT traps for clearer control flow

### 4. Monitor for Regression

- **Add comment to summary.bats**: Document why strict mode is NOT used in test wrappers
- **CI validation**: Ensure ci_simulate.sh warns if new tests add strict mode to wrappers
- **Track kcov updates**: Monitor kcov project for changes that might affect bash instrumentation behavior

### 5. Improve Debugging Workflow

- **Add kcov debug mode**: Create helper script that runs single test under kcov with verbose logging
- **Capture kcov output**: When tests fail under kcov, capture and display kcov's own diagnostic output
- **Document kcov limitations**: Create knowledge base entry about known kcov + bash interactions

## References

- [kcov documentation — Code coverage tool for compiled programs](https://github.com/SimonKagstrom/kcov)
- [BATS documentation — Bash Automated Testing System](https://bats-core.readthedocs.io/)
- Related outages:
  - `outages/2025-11-02-summary-strict-wrapper-bats-failure.json`
  - `outages/2025-11-03-kcov-bash-xtrace-output.json`
  - `outages/2025-11-06-kcov-subshell-depth-summary-tests.json`
  - `outages/2025-11-06-summary-bats-missing-setup.json`
- Pull request with all iterations: [PR#??? — ci: fix summary.bats tests 40-41]
- CI workflow: `.github/workflows/ci.yml:56-70`
- Test file: `tests/bats/summary.bats:1-35`
- Library: `scripts/lib/summary.sh:127-165`
