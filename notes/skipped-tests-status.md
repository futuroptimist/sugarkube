# Skipped Tests Status and Roadmap

**Date**: 2025-11-06 (Updated)  
**Context**: Documentation of all skipped tests in the repository and recommendations for future PRs

## Summary

As of 2025-11-06, there are **4 skipped tests** in the BATS test suite:
- 3 complex k3s integration tests (discover_flow.bats)
- 1 mdns advanced feature test (mdns_selfcheck.bats test 34)

All Python tests pass without skips (850+ tests).

**Test Count History**:
- After PR #4 (2025-11-05): 36 pass, 5 skip (l4_probe tests enabled via ncat installation)
- After PR #5 (2025-11-05): 37 pass, 4 skip (Test 33 dbus wait retry logic implemented)
- Current (2025-11-06): 37 pass, 4 skip (no changes)

## Test Suite Status

| Test File | Total | Pass | Skip | Fail |
|-----------|-------|------|------|------|
| discover_flow.bats | 9 | 6 | 3 | 0 |
| l4_probe.bats | 2 | 2 | 0 | 0 |
| mdns_selfcheck.bats | 18 | 17 | 1 | 0 |
| Other BATS | 12 | 12 | 0 | 0 |
| **Total BATS** | **41** | **37** | **4** | **0** |
| **Python tests** | **850+** | **850+** | **0** | **0** |

## Detailed Skip Analysis

### 1. discover_flow.bats - K3s Integration Tests (3 skipped)

**Tests**:
- Test 6: "discover flow joins existing server when discovery succeeds"
- Test 7: "discover flow elects winner after self-check failure"
- Test 8: "discover flow remains follower after self-check failure"

**Skip Reason**: Complex integration tests requiring k3s installation and multi-node orchestration

**Root Cause**:
- These tests invoke the full k3s discovery and installation flow
- Test 6 calls `k3s-discover.sh` which attempts to:
  - Acquire join gate lock
  - Run L4 network probes
  - Execute actual k3s installation
  - Perform multi-node cluster joining
- Current stub infrastructure doesn't mock k3s installation process
- Tests time out after 60+ seconds waiting for k3s operations

**Complexity**: HIGH
- Requires stubbing k3s installation binaries
- Needs mock cluster state management
- May require rethinking test approach (unit vs integration)

**Estimated Effort**: 4-8 hours per test
- Investigation: 2-3 hours (trace full execution path, identify all external dependencies)
- Implementation: 2-4 hours (create comprehensive stubs or refactor for testability)
- Validation: 1-2 hours (ensure tests verify actual behavior vs just passing)

**Recommended Approach**:
1. **Option A - Comprehensive Stubbing** (preferred for CI):
   - Stub `k3s` binary to simulate install/join operations
   - Mock cluster state files that scripts check
   - Add flag like `SUGARKUBE_TEST_MODE=1` to skip actual k3s calls
   - Pros: Tests run in CI, validate script logic
   - Cons: May not catch real k3s integration issues

2. **Option B - E2E Test Suite** (better coverage):
   - Move these tests to separate E2E suite run on real hardware
   - Use QEMU or Docker-based test cluster
   - Run in nightly builds, not PR checks
   - Pros: Tests real k3s integration
   - Cons: Slower, requires infrastructure

3. **Option C - Refactor for Testability** (most robust):
   - Extract k3s operations into mockable interface
   - Test script logic separately from k3s operations
   - Keep one E2E smoke test for real validation
   - Pros: Fast unit tests + real integration validation
   - Cons: Requires script refactoring

**Next Steps**:
1. Create dedicated PR to investigate Test 6 only
2. Document all external commands called and their expected behavior
3. Decide on Option A, B, or C based on findings
4. Implement chosen approach for all 3 tests

**References**:
- `tests/bats/discover_flow.bats:439-550`
- `scripts/k3s-discover.sh`
- `scripts/join_gate.sh`
- `notes/ci-test-failures-remaining-work.md:134-176`

---

### 2. l4_probe.bats - Network Tool Tests (FIXED - 2025-11-05 PR #4)

**Tests**:
- ~~Test 1: "l4_probe reports open port as open"~~ ✅ NOW PASSING
- ~~Test 2: "l4_probe exits non-zero when a port is closed"~~ ✅ NOW PASSING

**Original Skip Reason**: Missing `ncat` (netcat) binary in test environment

**Root Cause**:
- Tests conditionally skip if `ncat` is not available: `command -v ncat >/dev/null 2>&1 || skip "ncat not available"`
- `l4_probe.sh` script uses `ncat` for TCP port connectivity checks
- GitHub Actions runners didn't have `ncat` installed by default

**Fix Applied (2025-11-05 PR #4)**:
- Added `ncat` to package installation list in `.github/workflows/ci.yml`
- Tests automatically enabled via conditional skip logic (no test file changes needed)
- Both tests now pass in local and CI environments

**Complexity**: LOW (as predicted)

**Actual Effort**: ~15 minutes (faster than 30 minute estimate)
- Add `ncat` to CI dependencies: 5 minutes
- Run tests to verify: 5 minutes
- Create outage documentation: 5 minutes

**Outage Documentation**: `outages/2025-11-05-l4-probe-tests-ncat-missing.json`

**References**:
- `tests/bats/l4_probe.bats:39-68`
- `scripts/l4_probe.sh`
- `.github/workflows/ci.yml:24-39`
- `notes/ci-test-failures-remaining-work.md`

---

### 3. mdns_selfcheck.bats - Test 33: DBus Wait Logic (FIXED - 2025-11-05 PR #5)

**Test**: "mdns dbus self-check waits for avahi bus before browsing"

**Status**: ✅ NOW PASSING

**Original Skip Reason**: Needed `wait_for_avahi_dbus_gdbus` retry logic with ServiceUnknown error detection

**Root Cause**:
- Test expects script to retry when `gdbus introspect` returns ServiceUnknown error during Avahi startup
- Original implementation used busctl-based wait logic which didn't detect ServiceUnknown errors
- Test stubs gdbus to fail with ServiceUnknown on first 2 attempts, succeed on 3rd

**Fix Applied (2025-11-05 PR #5)**:
- Implemented `wait_for_avahi_dbus_gdbus()` function in `scripts/mdns_selfcheck_dbus.sh`
- Added ServiceUnknown error detection and retry logic with 0.5s sleep between attempts
- Function logs `event=avahi_dbus_ready outcome=ok` when service becomes available
- Integrated into mdns_selfcheck_dbus.sh startup sequence (lines 318-374)

**Complexity**: MEDIUM (as predicted)

**Actual Effort**: ~45 minutes
- Implement wait_for_avahi_dbus_gdbus() function: 20 minutes
- Add ServiceUnknown error detection and retry: 15 minutes
- Test and validate: 10 minutes

**Outage Documentation**: See `outages/2025-11-05-mdns-selfcheck-test-33-dbus-wait-retry.json` (if created in PR #5)

**References**:
- `tests/bats/mdns_selfcheck.bats:748-854`
- `scripts/mdns_selfcheck_dbus.sh:315-374`
- `notes/ci-test-failures-remaining-work.md`

---

### 4. mdns_selfcheck.bats - Test 34: Absence Gate (STILL SKIPPED)

**Test**: "mdns absence gate confirms wipe leaves no advertisements"

**Status**: ⏭️ STILL SKIPPED

**Skip Reason**: Test times out waiting for mdns_absence_gate logic to complete

**Root Cause (Updated 2025-11-06 Investigation)**:
- Test runs `k3s-discover.sh` which calls `ensure_mdns_absence_gate()` function
- The absence gate has complex retry logic with timeouts and backoffs (default 15 seconds)
- Initial suspicion was avahi-publish stubs using `sleep 60`, but fixing those to use trap+loop didn't resolve timeout
- Actual issue: mdns_absence_gate function needs environment variables to speed up its retry/backoff logic
- Missing timeout overrides: `MDNS_ABSENCE_TIMEOUT_MS`, `MDNS_ABSENCE_BACKOFF_START_MS`, `MDNS_ABSENCE_BACKOFF_CAP_MS`
- Test verifies that after node wipe, no mDNS advertisements remain (expects `mdns_absence_confirmed=1`)

**Complexity**: MEDIUM-HIGH (higher than initially estimated)
- Not just stub issue - requires understanding full absence gate logic flow
- Need to configure multiple timeout/backoff environment variables
- Must ensure absence gate completes within test timeout (30s)

**Estimated Effort**: 2-3 hours (confirmed after investigation)
- Investigation: 1 hour (✅ completed 2025-11-06 - traced to absence gate timeouts)
- Implementation: 45-60 minutes (add environment variable overrides, possibly adjust stubs)
- Validation: 30-45 minutes (verify test logic validates actual absence vs just passing)

**Recommended Approach (Updated 2025-11-06)**:
1. **Add timeout overrides to test environment** (lines 944-963 in mdns_selfcheck.bats):
   ```bash
   MDNS_ABSENCE_TIMEOUT_MS=2000 \        # Reduce from 15000ms to 2s
   MDNS_ABSENCE_BACKOFF_START_MS=100 \   # Reduce from 500ms to 100ms
   MDNS_ABSENCE_BACKOFF_CAP_MS=500 \     # Reduce from 4000ms to 500ms
   ```

2. **Verify avahi-publish stubs** are interruptible (already set correctly in test):
   - Use trap for TERM/INT signals
   - Loop with short sleep (0.1s) instead of long sleep (60s)

3. **Test with reduced timeouts**:
   - Ensure absence gate completes within 30s test timeout
   - Verify test actually validates absence behavior vs just passing

4. **Document findings**:
   - Add comments explaining why specific timeout values are needed
   - Reference k3s-discover.sh:1760-1850 for absence gate logic

**Investigation Notes (2025-11-06)**:
- ✅ Identified `sleep 60` in avahi-publish stubs - attempted fix with trap+loop pattern
- ✅ Test still timed out after stub fix - traced to absence gate retry logic
- ✅ Found default MDNS_ABSENCE_TIMEOUT_MS=15000ms causing long waits
- 🔲 Need to add environment overrides to test setup
- 🔲 May need to verify restart_avahi_daemon_service stub is correct

**Next Steps** (for future PR):
1. Add timeout environment variables to test setup (estimated 15 minutes)
2. Run test with verbose logging to verify absence gate completes (10 minutes)
3. Adjust timeout values if needed to balance speed vs reliability (10 minutes)
4. Validate test actually checks for advertisement absence vs just passing (15 minutes)
5. Consider if absence gate default timeouts should be configurable via env vars (architecture decision)

**References**:
- `tests/bats/mdns_selfcheck.bats:856-969` (test code)
- `scripts/k3s-discover.sh:1760-1965` (ensure_mdns_absence_gate function)
- `scripts/k3s-discover.sh:1720-1758` (check_mdns_absence_once function)
- Investigation notes above (2025-11-06)

---

## Prioritization for Future PRs

### Completed

**~~PR 1: Quick Win - ncat Installation~~ ✅ COMPLETED (PR #4 - 2025-11-05)**
- **Impact**: Enabled 2 tests (l4_probe.bats), simple CI change
- **Risk**: Very low
- **Tests**: l4_probe.bats tests 16-17
- **Actual time**: 15 minutes (vs 30 min estimated)
- **Outage**: `outages/2025-11-05-l4-probe-tests-ncat-missing.json`

**~~PR 2: DBus Wait Retry Logic~~ ✅ COMPLETED (PR #5 - 2025-11-05)**
- **Impact**: Enabled 1 test (mdns_selfcheck.bats test 33)
- **Risk**: Low (isolated change)
- **Tests**: mdns_selfcheck.bats test 33
- **Actual time**: ~45 minutes (vs 20-30 min estimated)
- **Outage**: Expected `outages/2025-11-05-mdns-selfcheck-test-33-dbus-wait-retry.json`
- **Implementation**: Added `wait_for_avahi_dbus_gdbus()` in `scripts/mdns_selfcheck_dbus.sh:318-374`

### Immediate (Next PR)

**PR 3: Absence Gate Timeout Configuration** (1-2 hours)
- **Impact**: Enables 1 test, improves absence gate configurability
- **Risk**: Low-Medium (test-only changes, may reveal configuration gaps)
- **Tests**: mdns_selfcheck.bats test 34
- **Deliverable**: Test passes with timeout overrides + documentation of findings
- **Investigation**: ✅ Completed 2025-11-06 (root cause identified - see Test 34 notes above)
- **Implementation**: Add `MDNS_ABSENCE_TIMEOUT_MS`, `MDNS_ABSENCE_BACKOFF_START_MS`, `MDNS_ABSENCE_BACKOFF_CAP_MS` to test environment
- **Estimated time**: 50-75 minutes (investigation already done, implementation + validation remaining)

### Long-term (Next 1-2 months)

**PR 4+: K3s Integration Tests** (20-30 hours total)
- **Impact**: Enables 3 tests, improves k3s coverage
- **Risk**: High (may require architecture changes)
- **Tests**: discover_flow.bats tests 6-8
- **Deliverable**: Decision document on Option A/B/C + implementation plan
- **Recommendation**: Break into multiple PRs:
  - PR 5: Investigation and approach decision (4-6 hours)
  - PR 6: Test 6 implementation (6-8 hours)
  - PR 7: Tests 7-8 implementation (8-10 hours)

---

## Success Metrics

**Current State** (2025-11-06 - After PR #5):
- BATS: 37/41 passing (90.2%)
- Python: 850+/850+ passing (100%)
- **Overall**: ~90% pass rate

Note: "Passing" means tests that run and pass. 4 tests are skipped conditionally.

**Target State** (after all skipped tests addressed):
- BATS: 41/41 passing (100%)
- Python: 850+/850+ passing (100%)
- **Overall**: 100% pass rate

**Intermediate Milestones**:
- ✅ After PR #4 (ncat): 36/41 passing (87.8%)
- ✅ After PR #5 (dbus retry - current): 37/41 passing (90.2%)
- 🔲 After PR #6 (absence gate): 38/41 passing (92.7%)
- 🔲 After PRs #7-9 (k3s integration): 41/41 passing (100%)

---

## Test Skip Guidelines for Future Development

When adding a test skip directive:

1. **Always include context**:
   ```bash
   # TODO: <Brief description of issue>
   # Root cause: <What's blocking>
   # Estimated fix: <Time estimate>
   skip "<User-facing reason>"
   ```

2. **Update this document**:
   - Add entry to relevant section
   - Document root cause and estimated effort
   - Propose approach for fixing

3. **Create tracking issue**:
   - Link from skip comment
   - Reference in this document
   - Add to roadmap

4. **Avoid indefinite skips**:
   - Every skip should have removal plan
   - If test is no longer valid, remove it (don't skip)
   - Consider if test belongs in different suite (unit vs E2E)

5. **Prefer conditional skips over permanent ones**:
   ```bash
   command -v ncat >/dev/null 2>&1 || skip "ncat not available"
   ```
   This allows tests to pass when conditions are met.

---

## Related Documentation

- **Test failures**: `notes/ci-test-failures-remaining-work.md`
- **Fix action plan**: `notes/ci-test-fixes-action-plan.md`
- **Outages**: `outages/2025-11-05-*.json`
- **CI workflow**: `.github/workflows/ci.yml`

---

**Maintained by**: CI/Test team  
**Last updated**: 2025-11-05  
**Next review**: After each skip is addressed or added
