# Skipped Tests Status and Roadmap

**Date**: 2025-11-07 (Updated)  
**Context**: Documentation of all skipped tests in the repository and recommendations for future PRs

## Summary

As of 2025-11-07, there are **3 skipped tests** in the BATS test suite:
- 3 complex k3s integration tests (discover_flow.bats Tests 6-8)

All Python tests pass without skips (850+ tests).

**Test Count History**:
- After PR #4 (2025-11-05): 36 pass, 5 skip (l4_probe tests enabled via ncat installation)
- After PR #5 (2025-11-05): 37 pass, 4 skip (Test 33 dbus wait retry logic implemented)
- After PR #6 (2025-11-07): 37 pass, 4 skip (Python 3.14 fixes)
- After PR #7 (2025-11-07): 38 pass, 3 skip (Test 34 absence gate + l4_probe confirmation)
- After PR #8 (2025-11-07): 38 pass, 3 skip (CI parity improvements - gdbus explicitly installed)

## Test Suite Status

| Test File | Total | Pass | Skip | Fail |
|-----------|-------|------|------|------|
| discover_flow.bats | 9 | 6 | 3 | 0 |
| l4_probe.bats | 2 | 2 | 0 | 0 |
| mdns_selfcheck.bats | 18 | 18 | 0 | 0 |
| Other BATS | 12 | 12 | 0 | 0 |
| **Total BATS** | **41** | **38** | **3** | **0** |
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
  - Execute actual k3s installation (downloads from https://get.k3s.io)
  - Perform multi-node cluster joining
- Current stub infrastructure doesn't mock k3s installation process
- Tests time out after 60+ seconds waiting for k3s operations

**Investigation Results (2025-11-07 PR #8)**:
- Attempted to add `SUGARKUBE_SKIP_K3S_INSTALL` environment variable to skip actual installation
- Test 6 initially passed with this approach
- Tests 7-8 entered infinite loops in bootstrap election and follower state machines
- Changes broke existing Test 5 (bootstrap publish flow - a previously passing test)
- **Conclusion**: Original 4-8 hour estimates per test are accurate; these require careful refactoring of control flow logic

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

### 2. l4_probe.bats - Network Tool Tests (COMPLETED - 2025-11-07 PR #7)

**Tests**:
- ~~Test 1: "l4_probe reports open port as open"~~ ✅ NOW PASSING
- ~~Test 2: "l4_probe exits non-zero when a port is closed"~~ ✅ NOW PASSING

**Original Skip Reason**: Missing `ncat` (netcat) binary in test environment

**Root Cause**:
- Tests conditionally skip if `ncat` is not available: `command -v ncat >/dev/null 2>&1 || skip "ncat not available"`
- `l4_probe.sh` script uses `ncat` for TCP port connectivity checks
- GitHub Actions runners have `ncat` installed (see .github/workflows/ci.yml:37)
- Tests were skipped in local environments without ncat but always passed in CI

**Status**: ✅ COMPLETED (2025-11-07 PR #7)
- Verified ncat is already in CI environment
- Tests pass automatically when ncat available (conditional skip logic)
- No code changes needed - this was a documentation issue only

**Complexity**: LOW

**Actual Effort**: ~5 minutes
- Verify ncat in CI: 2 minutes
- Run tests locally with ncat: 2 minutes
- Create outage documentation: 1 minute

**Outage Documentation**: `outages/2025-11-07-l4-probe-ncat-already-available.json`

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

### 4. mdns_selfcheck.bats - Test 34: Absence Gate (COMPLETED - 2025-11-07 PR #7)

**Test**: "mdns absence gate confirms wipe leaves no advertisements"

**Status**: ✅ NOW PASSING

**Original Skip Reason**: Test timed out waiting for mdns_absence_gate logic to complete

**Root Cause**: 
- Test runs `k3s-discover.sh` which calls `ensure_mdns_absence_gate()` function
- The absence gate has complex retry logic with timeouts and backoffs (default 15 seconds)
- Default MDNS_ABSENCE_TIMEOUT_MS=15000ms caused test to exceed 30s timeout
- avahi-publish stubs used `sleep 60 &` blocking calls that couldn't be interrupted
- Test expects `mdns_absence_confirmed=1` after node wipe leaves no mDNS advertisements

**Fix Applied (2025-11-07 PR #7)**:
1. Added timeout environment variables to test setup:
   - `MDNS_ABSENCE_TIMEOUT_MS=2000` (reduced from 15000ms)
   - `MDNS_ABSENCE_BACKOFF_START_MS=100` (reduced from 500ms)
   - `MDNS_ABSENCE_BACKOFF_CAP_MS=500` (reduced from 4000ms)

2. Refactored avahi-publish stubs to use trap handlers:
   ```bash
   trap 'exit 0' TERM INT
   while true; do
     sleep 0.1
   done
   ```
   Instead of non-interruptible `sleep 60 &`

**Result**: Test now completes in ~3-4 seconds instead of timing out

**Complexity**: MEDIUM (investigation already done in notes)

**Actual Effort**: ~15 minutes
- Apply timeout overrides: 5 minutes
- Fix stub trap handlers: 5 minutes
- Test and validate: 5 minutes

**Outage Documentation**: `outages/2025-11-07-mdns-absence-gate-timeout-fix.json`

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
- **Note**: Tests were already passing in CI (ncat already installed), just skipped locally

**~~PR 2: DBus Wait Retry Logic~~ ✅ COMPLETED (PR #5 - 2025-11-05)**
- **Impact**: Enabled 1 test (mdns_selfcheck.bats test 33)
- **Risk**: Low (isolated change)
- **Tests**: mdns_selfcheck.bats test 33
- **Actual time**: ~45 minutes (vs 20-30 min estimated)
- **Outage**: Expected `outages/2025-11-05-mdns-selfcheck-test-33-dbus-wait-retry.json`
- **Implementation**: Added `wait_for_avahi_dbus_gdbus()` in `scripts/mdns_selfcheck_dbus.sh:318-374`

**~~PR 3: Absence Gate Timeout Configuration~~ ✅ COMPLETED (PR #7 - 2025-11-07)**
- **Impact**: Enabled 1 test (mdns_selfcheck.bats test 34)
- **Risk**: Low (test-only changes)
- **Tests**: mdns_selfcheck.bats test 34
- **Deliverable**: Test passes with timeout overrides + stub refactoring
- **Investigation**: ✅ Completed 2025-11-06 (root cause identified)
- **Implementation**: Added timeout env vars + trap-based stubs
- **Estimated time**: 50-75 minutes (from notes)
- **Actual time**: 15 minutes (much faster than estimate!)
- **Outage**: `outages/2025-11-07-mdns-absence-gate-timeout-fix.json`

### Immediate (No PRs Needed)

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

**Current State** (2025-11-07 - After PR #7):
- BATS: 38/41 passing (92.7%)
- Python: 850+/850+ passing (100%)
- **Overall**: ~93% pass rate (combined BATS+Python)

Note: "Passing" means tests that run and pass. 3 tests are skipped conditionally.

**Target State** (after all skipped tests addressed):
- BATS: 41/41 passing (100%)
- Python: 850+/850+ passing (100%)
- **Overall**: 100% pass rate

**Intermediate Milestones**:
- ✅ After PR #4 (ncat): 36/41 passing (87.8%)
- ✅ After PR #5 (dbus retry): 37/41 passing (90.2%)
- ✅ After PR #6 (python 3.14): 37/41 passing (90.2%)
- ✅ After PR #7 (absence gate - current): 38/41 passing (92.7%)
- 🔲 After PRs #8-10 (k3s integration): 41/41 passing (100%)

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
**Last updated**: 2025-11-07 
**Next review**: After each skip is addressed or added
