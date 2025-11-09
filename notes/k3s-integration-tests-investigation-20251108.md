# K3s Integration Tests Investigation - 2025-11-08

**Context**: Investigation attempt to enable Tests 5-7 in discover_flow.bats  
**Time spent**: 20 minutes  
**Result**: ✅ COMPLETED (2025-11-09) - All tests now passing!  
**Next steps**: ~~Document findings for future work~~ DONE - Tests fixed in PRs #9, #10, #11

## Final Outcome (2025-11-09)

**ALL 3 TESTS NOW PASSING!** 🎉

This investigation (conducted 2025-11-08) identified the correct approach:
1. Stub k3s installation (via `SUGARKUBE_K3S_INSTALL_SCRIPT`)
2. Add missing stubs for external dependencies
3. Test decision logic, not installation

**Actual implementation time** (2025-11-09):
- PR #9 (Test 6): 15 minutes - extended systemctl stub
- PR #10 (Test 5): 35 minutes - added missing stubs from Test 6 pattern
- PR #11 (Test 7): 30 minutes - added missing stubs, removed timeout stub
- **Total**: ~80 minutes vs originally estimated 12-24 hours

---

## Original Investigation Summary (2025-11-08)

### Approach Taken

Added `SUGARKUBE_SKIP_K3S_INSTALL` environment variable to skip actual k3s installation during tests.

**Changes made**:
1. Modified `scripts/k3s-discover.sh` to check `SUGARKUBE_SKIP_K3S_INSTALL` flag
2. Added conditional logic around 4 `curl -sfL https://get.k3s.io` calls (lines 3202, 3251, 3437, 3553)
3. Added conditional logic to skip `wait_for_api()` calls when k3s install skipped
4. Updated tests to set `SUGARKUBE_SKIP_K3S_INSTALL=1`
5. Removed skip directives from tests 6-8

### Issues Encountered

**Test 6**: "discover flow joins existing server when discovery succeeds"
- Test hangs indefinitely even with k3s install skipped  
- Exit status check fails: `[ "$status" -eq 0 ]` at line 470
- Script exits early due to `configure_avahi.sh` failure (exit code 1)
- Issue: Tests expect additional stubs beyond just k3s installation

**Root Cause Analysis**:
- Even with k3s install skipped, the discover flow script still calls many external dependencies
- `configure_avahi.sh` is called and expects to modify system files
- Test has `configure_stub` but may need additional environment setup
- Script may be entering infinite loops in discovery/election logic when API isn't available

### Key Findings

1. **Multiple dependencies beyond k3s install**:
   - `configure_avahi.sh` - Avahi configuration
   - `wait_for_avahi_dbus.sh` - D-Bus readiness checks
   - `join_gate.sh` - Lock acquisition/release
   - `l4_probe.sh` - Network connectivity checks
   - `elect_leader.sh` - Bootstrap election logic

2. **Test infrastructure gaps**:
   - Tests have partial stubs (common network tools, curl, timeout)
   - Missing stubs for full discovery flow
   - No mock cluster state management

3. **Script control flow complexity**:
   - Discover script has multiple phases: single/cluster-init/join/agent
   - Each phase has different expectations
   - Bootstrap election logic may loop if API wait is skipped

### Implementation Attempts

**Attempt 1**: Skip k3s install only
- Result: Tests still timeout
- Problem: API wait logic still runs, expects k3s API

**Attempt 2**: Skip both k3s install and API wait
- Result: Tests hang (did not complete in 60 seconds)
- Problem: Unknown - needs further investigation with verbose logging

### Recommended Next Steps

#### Short-term (for next PR attempt)

1. **Add verbose logging** to understand where tests hang:
   ```bash
   export LOG_LEVEL=debug
   export SUGARKUBE_TRACE=1
   ```

2. **Run test with timeout and capture full output**:
   ```bash
   timeout 10 bats -f "discover flow joins existing server" tests/bats/discover_flow.bats > /tmp/test6-output.log 2>&1
   ```

3. **Identify hanging point** from logs:
   - Look for last log message before hang
   - Identify which external command or loop is blocking

4. **Add missing stubs** for identified dependencies

5. **Consider additional skip flags**:
   - `SUGARKUBE_SKIP_AVAHI_CONFIG=1` - Skip Avahi configuration
   - `SUGARKUBE_SKIP_JOIN_GATE=1` - Skip lock acquisition
   - `SUGARKUBE_SKIP_L4_PROBE=1` - Skip network connectivity checks

#### Long-term (architectural approach)

See `notes/skipped-tests-status.md` section 1 for full analysis. Three options:

**Option A - Comprehensive Stubbing** (test in CI):
- Stub all external dependencies
- Mock cluster state files
- Add `SUGARKUBE_TEST_MODE=1` master flag
- Estimated: 4-6 hours

**Option B - E2E Test Suite** (test on real hardware):
- Move to separate E2E suite
- Use QEMU or Docker-based test cluster
- Run in nightly builds
- Estimated: 8-12 hours

**Option C - Refactor for Testability** (best long-term):
- Extract k3s operations into mockable interface
- Separate script logic from external calls
- Keep one E2E smoke test
- Estimated: 12-16 hours

### Files Modified (Reverted)

All changes reverted due to tests hanging:
- `scripts/k3s-discover.sh` - Added SUGARKUBE_SKIP_K3S_INSTALL checks (4 locations)
- `tests/bats/discover_flow.bats` - Removed skip directives, added env var (3 tests)

### Lessons Learned

1. **Initial estimates (4-8 hours per test) were accurate** - Tests have deep dependencies
2. **Skipping k3s install is insufficient** - Many other external calls need stubbing
3. **Tests may have infinite loops** - Needs investigation with verbose logging
4. **20-minute attempt validates complexity** - These tests genuinely require dedicated PRs

### Time Breakdown

- Reading test structure and script: 5 minutes
- Implementing SUGARKUBE_SKIP_K3S_INSTALL: 8 minutes
- Testing and debugging: 5 minutes  
- Documentation: 2 minutes
- **Total**: 20 minutes

### Conclusion

The 20-minute attempt confirms that these tests are genuinely complex integration tests requiring more than a quick fix. The original 4-8 hour estimates in the notes are accurate.

**Recommendation**: Do not attempt these tests in time-constrained PRs. Instead, focus on:
1. Documentation improvements (like this investigation report)
2. Low-hanging fruit fixes (already completed - 38/41 tests passing)
3. Infrastructure improvements that make future work easier

This investigation provides a foundation for future work and validates the "partial progress" approach outlined in the problem statement.
