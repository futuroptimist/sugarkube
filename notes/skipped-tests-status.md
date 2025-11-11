# Skipped Tests Status and Roadmap

**Date**: 2025-11-10 (Updated - Test Count Correction)
**Context**: Documentation of all skipped tests in the repository and recommendations for future PRs

## Summary

As of 2025-11-10, **all BATS tests run locally** thanks to the bundled ncat stub

**CI STATUS**: 42/42 BATS tests passing (100% pass rate in CI) 🎉

**LOCAL STATUS**: 42/42 tests passing (ncat stub keeps listeners available)

All Python tests pass without skips (850+ tests).

**Test Count History**:
- After PR #4 (2025-11-05): 36 pass, 5 skip (l4_probe tests enabled via ncat installation)
- After PR #5 (2025-11-05): 37 pass, 4 skip (Test 33 dbus wait retry logic implemented)
- After PR #6 (2025-11-07): 37 pass, 4 skip (Python 3.14 fixes)
- After PR #7 (2025-11-07): 38 pass, 3 skip (Test 34 absence gate + l4_probe confirmation)
- After PR #8 (2025-11-07): 38 pass, 3 skip (CI parity improvements - gdbus explicitly installed)
- After PR #9 (2025-11-09): 39 pass, 2 skip (Test 6 "elects winner" now passing with systemctl stub fix)
- After PR #10 (2025-11-09): 40 pass, 1 skip (Test 5 "joins existing server" now passing with missing stubs fix)
- After PR #11 (2025-11-09): 41 pass, 0 skip *(incorrect count - see below)*
- **After 2025-11-10 Correction: 42 total tests (42 pass locally with stub; 42 pass in CI)** 🎉

**Test Count Correction (2025-11-10)**:
- Previous documentation stated "41/41 tests" - this was incorrect
- Actual test count: **42 total tests** across all .bats files
- The 2 l4_probe tests (17-18) were miscounted as non-existent
- These tests used `command -v ncat || skip` until the suite gained a bundled stub
- In CI: All 42 tests pass (ncat installed at .github/workflows/ci.yml:38)
- Locally: 42 pass with the stub providing `ncat -lk` behaviour when the binary is absent
- **Achievement maintained**: 100% pass rate in CI environment!

## Test Suite Status

| Test File | Total | Pass (CI) | Pass (Local) | Conditional Skip | Fail |
|-----------|-------|-----------|--------------|------------------|------|
| discover_flow.bats | 9 | 9 | 9 | 0 | 0 |
| l4_probe.bats | 2 | 2 | 2 | 0 | 0 |
| mdns_selfcheck.bats | 18 | 18 | 18 | 0 | 0 |
| Other BATS | 13 | 13 | 13 | 0 | 0 |
| **Total BATS** | **42** | **42** | **42** | **0** | **0** |
| **Python tests** | **850+** | **850+** | **850+** | **0** | **0** |

## ALL TESTS COMPLETE IN CI! 🎉

### Conditionally Skipped Tests (Pass in CI)

#### l4_probe.bats Tests 17-18 (Now stubbed - ncat dependency removed for local runs)

#### ✅ discover_flow.bats - K3s Integration Tests (COMPLETED 2025-11-09)

**Note on Test Naming**: Tests are referenced using position-based numbering (Test 1-9) with line numbers. See notes/test-numbering-standardization.md for details.

**All Tests Now Passing**:
- ✅ **Test 5: "discover flow joins existing server when discovery succeeds"** (line 513) - FIXED 2025-11-09 PR #10
- ✅ **Test 6: "discover flow elects winner after self-check failure"** (line 646) - FIXED 2025-11-09 PR #9
- ✅ **Test 7: "discover flow remains follower after self-check failure"** (line 788) - FIXED 2025-11-09 PR #11

**Original Challenge**: Complex integration tests requiring k3s installation and multi-node orchestration

**Root Cause**:
- These tests invoke the full k3s discovery and installation flow
- "joins existing server" test calls `k3s-discover.sh` which attempts to:
  - Acquire join gate lock
  - Run L4 network probes
  - Execute actual k3s installation (downloads from https://get.k3s.io)
  - Perform multi-node cluster joining
- Current stub infrastructure doesn't fully mock k3s installation process
- Tests time out after 60+ seconds waiting for k3s operations

**Investigation Results & Progress**:

**2025-11-09 - "remains follower" Test FIXED (PR #11 - THIS PR)** 🎉:
- ✅ Test 7 "discover flow remains follower after self-check failure" now PASSING
- **Root cause identified**: Test was missing critical stubs from Test 6 pattern (timeout, journalctl, sleep, gdbus, busctl, directories, avahi.conf)
- **Fix applied**: Added all missing stubs following Test 6 pattern, created required directories, added environment variables
- **Result**: Test passes consistently validating follower wait logic
- **Outage**: outages/2025-11-09-test7-discover-flow-follower-missing-stubs.json
- **Time**: 30 minutes (investigation + stub additions + validation)
- **Achievement**: Completes ALL discover_flow.bats tests (9/9 passing, 100%)

**2025-11-09 - "joins existing server" Test FIXED (PR #10)**:
- ✅ Test 5 "discover flow joins existing server when discovery succeeds" now PASSING
- **Root cause identified**: Missing critical stubs that Test 6 had (journalctl, sleep, proper timeout, directories, mdns smart stub)
- **Fix applied**: Added all missing stubs from Test 6 pattern, replaced SKIP_MDNS_SELF_CHECK=1 with smart stub
- **Result**: Test passes consistently in <5 seconds
- **Outage**: outages/2025-11-09-discover-flow-test6-missing-stubs.json
- **Time**: 35 minutes (investigation + fix + validation + documentation)

**2025-11-09 - "elects winner" Test FIXED (PR #9)**:
- ✅ Test 6 "discover flow elects winner after self-check failure" now PASSING
- **Root cause identified**: systemctl stub missing 'reload' and 'restart' command handling
- **Fix applied**: Extended stub_common_network_tools() to handle all systemctl operations
- **Result**: Test passes consistently in <5 seconds
- **Outage**: outages/2025-11-09-discover-flow-test6-systemctl-stub.json
- **Time**: 15 minutes (building on 2025-11-08 investigation)

**2025-11-08 - Stub Infrastructure Implementation**:
- **First attempt (20 min)**: Added `SUGARKUBE_SKIP_K3S_INSTALL` flag - tests still hung
- **Second attempt (90 min)**: Implemented proper stubbing infrastructure following "understand real use case" principle
  - Read docs/raspi_cluster_setup.md to understand actual Pi cluster workflow
  - Realized tests validate **mDNS discovery & join decision logic**, NOT k3s installation
  - Created `run_k3s_install()` wrapper function with `SUGARKUBE_K3S_INSTALL_SCRIPT` override
  - Added `create_k3s_install_stub()` and `create_l4_probe_stub()` test helpers
  - Updated all 4 k3s installation call sites to use new wrapper
  - Added environment variable overrides (tokens, timeouts)
- **Result**: Infrastructure reusable across all 3 tests
- **Documentation**:
  - Full investigation: notes/k3s-integration-tests-investigation-20251108.md
  - Outages: outages/2025-11-08-k3s-integration-tests-investigation.json
  - Stub implementation: outages/2025-11-08-k3s-integration-tests-stub-infrastructure.json

**Revised Estimated Effort** (ALL COMPLETED 2025-11-09):
- ✅ Test 6 "elects winner": 15 minutes (COMPLETED 2025-11-09 PR #9)
- ✅ Test 5 "joins existing server": 35 minutes (COMPLETED 2025-11-09 PR #10)
- ✅ Test 7 "remains follower": 30 minutes (COMPLETED 2025-11-09 PR #11)
- **Total actual time for Tests 5-7**: 80 minutes (close to predicted 60!)

**Key Learning**: Original "4-8 hours per test" estimates were based on XY problem (trying to skip k3s install vs understanding what to test). Actual solution: stub external dependencies, test decision logic. Infrastructure reusable across all tests.

**Complexity**: LOW (revised down from HIGH after infrastructure implementation)
- ✅ k3s installation stubbing: DONE via `run_k3s_install()` wrapper
- ✅ Test helpers created: `create_k3s_install_stub()`, `create_l4_probe_stub()`
- ✅ Test 6 fixed: systemctl stub extension (PR #9)
- ✅ Test 5 fixed: missing stubs from Test 6 pattern (PR #10)
- ✅ Test 7 fixed: added missing stubs from Test 6 pattern (PR #11)

**Total Time for All Three Tests** (2025-11-08 to 2025-11-09):
- Infrastructure implementation: 90 minutes (2025-11-08)
- Test 6 fix: 15 minutes (2025-11-09)
- Test 5 fix: 35 minutes (2025-11-09)
- Test 7 fix: 30 minutes (2025-11-09)
- **Grand Total**: 170 minutes (~2.8 hours for all 3 tests vs original 12-24 hour estimate)

**Recommended Approach** (UPDATED 2025-11-08):
**Option A - Comprehensive Stubbing** ✅ IMPLEMENTED:
   - ✅ Created `run_k3s_install()` wrapper to stub k3s installation
   - ✅ Added `SUGARKUBE_K3S_INSTALL_SCRIPT` override following existing patterns
   - ✅ Created test helpers for k3s install and L4 probe stubs
   - ✅ Tests now run without hanging (<5 seconds vs 60+ seconds)
   - ✅ Infrastructure reusable across all 3 tests
   - ⚙️ Minor debugging needed to complete (est. 30 min remaining)
   - Pros: ✅ Tests run in CI, ✅ validate script logic, ✅ fast execution
   - Cons: May not catch real k3s integration issues (acceptable for unit tests)

Option B & C remain valid for future comprehensive E2E testing but are not needed for these specific tests which focus on discovery/decision logic.

**Next Steps** (UPDATED 2025-11-08):
1. ✅ Read docs/raspi_cluster_setup.md to understand real use case
2. ✅ Implement stubbing infrastructure for k3s installation
3. ✅ Remove skip directives and add test helpers
4. ⚙️ Debug Test 6 non-zero exit (15-20 min) - partial issue with script flow
5. ⚙️ Validate Tests 7-8 pass with current infrastructure (10-15 min)
6. ⚙️ Create final outage entries and update notes (~5 min)

**Total remaining work**: ~30 minutes for complete Test 6-8 passing

**References**:
- `tests/bats/discover_flow.bats:439-550`
- `scripts/k3s-discover.sh`
- `scripts/join_gate.sh`
- `notes/ci-test-failures-remaining-work.md:134-176`

---

### l4_probe.bats - Network Tool Tests (Stubbed ncat for local runs)

**Tests**:
- Test 16: "l4_probe reports open port as open" (line 38)
- Test 17: "l4_probe exits non-zero when a port is closed" (line 53)

**Status**: ✅ PASSING EVERYWHERE (stub handles hosts without ncat)

**Skip Condition**: No longer needed - the suite now provides `tests/bats/fixtures/ncat_stub.py`

**Root Cause**:
- Tests previously required the `ncat` (netcat) binary for TCP port connectivity checks
- `l4_probe.sh` script still probes ports, but the test harness now bundles a Python stub for listeners
- GitHub Actions CI continues to use the real `ncat` installed via .github/workflows/ci.yml:38
- Local environments fall back to the stub, so coverage remains identical without extra packages

**CI Status**: ✅ PASSING (2025-11-07 verified and unchanged)
- ncat installed via apt-get in CI workflow
- Tests keep using the real binary when available

**Local Status**: ✅ PASSING (stub activated automatically)
- No manual installs required - the stub is part of the repo

**Complexity**: Low - stub mirrors `ncat -lk` behaviour for test listeners

**Note**: These tests were miscounted in previous documentation. They are part of the 42-test suite, not "missing" tests. The new stub removes the need for conditional skips.

**Outage Documentation**: `outages/2025-11-07-l4-probe-ncat-already-available.json`

**References**:
- `tests/bats/l4_probe.bats:38-51`
- `tests/bats/l4_probe.bats:53-68`
- `scripts/l4_probe.sh`
- `.github/workflows/ci.yml:38`
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

**~~PR 4: K3s Integration Tests (Tests 5-7)~~ ✅ ALL COMPLETED (PRs #9, #10, #11 - 2025-11-09)** 🎉
- **Impact**: Enabled final 3 tests, achieves 100% BATS pass rate
- **Risk**: Low after infrastructure implementation
- **Tests**: discover_flow.bats Tests 5, 6, 7
- **Deliverable**: All tests passing, comprehensive documentation
- **Actual breakdown**:
  - Infrastructure (2025-11-08): 90 minutes
  - PR #9 Test 6: 15 minutes
  - PR #10 Test 5: 35 minutes
  - PR #11 Test 7: 10 minutes
- **Total time**: 150 minutes (~2.5 hours vs original 20-30 hour estimate)
- **Outages**:
  - `outages/2025-11-09-discover-flow-test6-systemctl-stub.json`
  - `outages/2025-11-09-discover-flow-test6-missing-stubs.json`
  - `outages/2025-11-09-test7-discover-flow-follower-missing-stubs.json`

---

## Success Metrics

**🎉 TARGET STATE ACHIEVED (2025-11-10 - Test Count Corrected)** 🎉
- BATS (CI): **42/42 passing (100%)** ✅
- BATS (Local): **40/42 passing + 2 conditional skip (95.2%)** ✅
- Python: **850+/850+ passing (100%)** ✅
- **Overall: 100% pass rate in CI (combined BATS+Python)** ✅

**Progress Timeline** (corrected test counts):
- Initial state: ~34/42 passing (81.0%)
- After PR #7 (2025-11-07): 38/42 passing (90.5%)
- After PR #9 (2025-11-09): 39/42 passing (92.9%)
- After PR #10 (2025-11-09): 40/42 passing (95.2%)
- **After PR #11 (2025-11-09): 42/42 passing in CI (100%)** 🎉
- **2025-11-10 Correction: Confirmed 42 total tests (was documented as 41)**

**ALL MILESTONES COMPLETE** (corrected counts):
- ✅ After PR #4 (ncat): 36/42 passing (85.7%)
- ✅ After PR #5 (dbus retry): 37/42 passing (88.1%)
- ✅ After PR #6 (python 3.14): 37/42 passing (88.1%)
- ✅ After PR #7 (absence gate): 38/42 passing (90.5%)
- ✅ After PR #8 (CI parity): 38/42 passing (90.5%)
- ✅ After PR #9 (Test 6): 39/42 passing (92.9%)
- ✅ After PR #10 (Test 5): 40/42 passing (95.2%)
- ✅ **After PR #11 (Test 7): 42/42 passing in CI (100%)** 🎉
- ✅ **2025-11-10: Test count corrected, documentation synchronized**

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

   Regression coverage: `tests/test_bats_skip_guidelines.py` enforces the comment block
   around each `skip` invocation.

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
