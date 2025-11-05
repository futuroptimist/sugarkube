# Skipped Tests Status and Roadmap

**Date**: 2025-11-05  
**Context**: Documentation of all skipped tests in the repository and recommendations for future PRs

## Summary

As of 2025-11-05 (Updated PR #4), there are **5 skipped tests** in the BATS test suite:
- 3 complex k3s integration tests (discover_flow.bats)
- 2 mdns advanced feature tests (mdns_selfcheck.bats tests 33-34)

All Python tests pass without skips (850+ tests).

**Test Count Impact of This PR**:
- Before PR #4: 36 pass, 5 skip (l4_probe tests were skipped)
- After PR #4: 38 pass, 5 skip (l4_probe tests now passing)
- Net improvement: +2 passing tests

## Test Suite Status

| Test File | Total | Pass | Skip | Fail |
|-----------|-------|------|------|------|
| discover_flow.bats | 9 | 6 | 3 | 0 |
| l4_probe.bats | 2 | 2 | 0 | 0 |
| mdns_selfcheck.bats | 18 | 16 | 2 | 0 |
| Other BATS | 12 | 12 | 0 | 0 |
| **Total BATS** | **41** | **36** | **5** | **0** |
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

### 3. mdns_selfcheck.bats - Tests 33-34: Advanced Features (2 skipped)

#### Test 33: DBus Wait Logic

**Test**: "mdns dbus self-check waits for avahi bus before browsing"

**Skip Reason**: Needs `wait_for_avahi_dbus` retry logic with ServiceUnknown error detection

**Root Cause**:
- Test expects script to retry when `gdbus introspect` returns ServiceUnknown error
- Current implementation may not have retry logic or uses different tool (busctl)
- Test stubs gdbus to fail with ServiceUnknown on first 2 attempts, succeed on 3rd
- Script doesn't implement the expected retry behavior

**Complexity**: MEDIUM
- Need to implement new wait function using gdbus
- Coordinate with existing busctl-based wait logic
- Handle multiple gdbus error types (ServiceUnknown vs others)

**Estimated Effort**: 20-30 minutes (per notes investigation)
- Implement `wait_for_avahi_dbus_gdbus()` function: 10 minutes
- Add ServiceUnknown error detection and retry: 10 minutes
- Test and validate: 10 minutes

**Recommended Approach**:
1. Add new retry function in `scripts/mdns_selfcheck_dbus.sh`:
   ```bash
   wait_for_avahi_dbus_gdbus() {
     local max_attempts=10
     local attempt=0
     while [ $attempt -lt $max_attempts ]; do
       attempt=$((attempt + 1))
       if gdbus introspect --system --dest org.freedesktop.Avahi --object-path / >/dev/null 2>&1; then
         log_info mdns_selfcheck event=avahi_dbus_ready outcome=ok attempts=$attempt
         return 0
       fi
       local error_output
       error_output="$(gdbus introspect --system --dest org.freedesktop.Avahi --object-path / 2>&1 || true)"
       if [[ "$error_output" =~ ServiceUnknown ]]; then
         log_debug mdns_selfcheck event=avahi_dbus_wait attempt=$attempt status=not_ready
         sleep 0.5
         continue
       fi
       log_error mdns_selfcheck event=avahi_dbus_error attempt=$attempt
       return 1
     done
     log_error mdns_selfcheck event=avahi_dbus_timeout attempts=$max_attempts
     return 1
   }
   ```

2. Call before ServiceBrowserNew attempt
3. Make conditional on gdbus availability

**Next Steps**:
1. Create focused PR implementing just this retry logic
2. Reference `notes/ci-test-fixes-action-plan.md` lines 650-731 for detailed implementation
3. Test with both success and failure scenarios

**References**:
- `tests/bats/mdns_selfcheck.bats:748-860`
- `scripts/mdns_selfcheck_dbus.sh`
- `scripts/wait_for_avahi_dbus.sh`
- `notes/ci-test-fixes-action-plan.md:650-731`

---

#### Test 34: Absence Gate

**Test**: "mdns absence gate confirms wipe leaves no advertisements"

**Skip Reason**: Test times out - needs investigation of wipe/cleanup flow

**Root Cause**:
- Test verifies that after node wipe, no mDNS advertisements remain
- Timeout suggests missing stubs for cleanup/verification commands
- May require stubbing wipe scripts or cleanup verification tools

**Complexity**: MEDIUM-HIGH
- Need to trace full wipe and verification flow
- Identify which commands cause timeout
- Understand expected vs actual wipe behavior

**Estimated Effort**: 2-3 hours
- Investigation: 1-1.5 hours (trace execution, identify hanging commands)
- Implementation: 45-60 minutes (add missing stubs)
- Validation: 30 minutes (verify test logic is sound)

**Recommended Approach**:
1. **Investigation Phase**:
   - Run test with `timeout 30` and capture output
   - Add debug logging to wipe scripts
   - Identify which command hangs (likely avahi or systemctl operations)

2. **Implementation Phase**:
   - Add stubs for wipe-related commands (likely similar to join_gate fixes)
   - Ensure cleanup verification commands are stubbed
   - May need to stub file system operations if wipe checks files

3. **Validation Phase**:
   - Verify test actually validates wipe behavior (not just passing)
   - Consider if test expectations match implementation
   - Document any assumptions about wipe completeness

**Next Steps**:
1. Create investigation PR focused only on Test 34
2. Run with verbose logging and capture full output
3. Document findings and update this file
4. Implement stubs based on findings
5. Consider if test should be part of E2E suite instead

**References**:
- `tests/bats/mdns_selfcheck.bats:861-900`
- `scripts/wipe_node.sh`
- Related scripts that handle cleanup

---

## Prioritization for Future PRs

### Immediate (Next 1-2 PRs)

**~~PR 1: Quick Win - ncat Installation~~ ✅ COMPLETED (PR #4 - 2025-11-05)**
- **Impact**: Enabled 2 tests, simple CI change
- **Risk**: Very low
- **Tests**: l4_probe.bats tests 1-2
- **Actual time**: 15 minutes (vs 30 min estimated)
- **Outage**: `outages/2025-11-05-l4-probe-tests-ncat-missing.json`

**PR 2: DBus Wait Retry Logic** (30 minutes)
- **Impact**: Enables 1 test, well-scoped feature
- **Risk**: Low (isolated change)
- **Tests**: mdns_selfcheck.bats test 33
- **Deliverable**: Documented in action plan with exact implementation

### Short-term (Next 2-4 weeks)

**PR 3: Absence Gate Investigation** (3 hours)
- **Impact**: Enables 1 test
- **Risk**: Medium (may reveal design issues)
- **Tests**: mdns_selfcheck.bats test 34
- **Deliverable**: Either fix + test pass, or documented decision to move to E2E

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

**Current State** (2025-11-05 - After PR #4):
- BATS: 36/41 passing (87.8%)
- Python: 850+/850+ passing (100%)
- **Overall**: ~88% pass rate

Note: "Passing" means tests that run and pass. 5 tests are skipped conditionally.

**Target State** (after all skipped tests addressed):
- BATS: 41/41 passing (100%)
- Python: 850+/850+ passing (100%)
- **Overall**: 100% pass rate

**Intermediate Milestones**:
- ✅ After PR #4 (ncat - THIS PR): 36/41 passing (87.8%)
- After PR #5 (dbus retry): 37/41 passing (90.2%)
- After PR #6 (absence gate): 38/41 passing (92.7%)
- After PRs #7-9 (k3s integration): 41/41 passing (100%)

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
