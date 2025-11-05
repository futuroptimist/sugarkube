# CI Workflow Test Failures - Remaining Work

This document tracks the remaining test failures that need to be addressed after the initial fixes in this PR.

## Summary of Fixes Applied

### ✅ Completed (17 tests fixed - updated 2025-11-05)
1. **mdns_wire_probe.bats** - 4/4 tests now passing
   - Fixed by adding `ALLOW_NON_ROOT=1` environment variable
   - Root cause documented in `outages/2025-11-04-mdns-test-missing-allow-non-root.json`

2. **mdns_selfcheck.bats** - 15/18 tests now passing (was 10/18)
   - Tests 1-7, 9-14: Previously fixed with curl stubs and assertions
   - Test 3 (NEW): Fixed by changing log level from debug to info for enumeration warnings
   - Root causes documented in:
     - `outages/2025-11-04-mdns-test-missing-curl-stub.json`
     - `outages/2025-11-04-mdns-test-incorrect-assertion.json`
     - `outages/2025-11-05-mdns-selfcheck-test-03-enum-warn-log-level.json` (NEW)

3. **join_gate.bats** - 2/2 tests now passing (NEW 2025-11-05)
   - Both tests fixed by adding systemctl, gdbus, and busctl stubs
   - Tests were timing out waiting for avahi-daemon via systemctl
   - Root cause documented in `outages/2025-11-05-join-gate-missing-dbus-stubs.json`

## Remaining Test Failures

### 🔄 mdns_selfcheck.bats (8 tests remaining - COMPLEXITY UPDATED)

**Status as of 2025-11-05**: After investigation of remaining tests, discovered higher complexity than initially assessed. See `ci-test-fixes-action-plan.md` section "Investigation Findings (2025-11-05)" for detailed analysis.

**Critical Discovery**: Tests 8, 15, and 16 require non-trivial changes:
- **Test 8** (line 370): Fixture role mismatch + resolution status code issues (2-3 hrs)
- **Test 15** (line 582): Requires browse flow restructuring for dbus preference (3-4 hrs)
- **Test 16** (line 623): Requires new gdbus-based wait implementation (3-4 hrs)

See action plan for detailed root cause analysis and recommended approaches.

**Tests now passing (as of 2025-11-05):**
1. ✅ Line 158 (Test 3): "mdns self-check warns when enumeration misses but browse succeeds" - Fixed by changing log level from debug to info
2. ✅ Line 254 (Test 5): "mdns self-check strips surrounding quotes before matching" - Already passing
3. ✅ Line 293 (Test 6): "mdns self-check accepts short host when EXPECTED_HOST has .local" - Already passing
4. ✅ Line 476 (Test 11): "mdns self-check tolerates extra avahi-browse fields and anchors by type" - Already passing

### ✅ join_gate.bats (2 tests - COMPLETED 2025-11-05)

**Status**: All tests now passing

**Root Cause**: Tests timed out waiting for avahi-daemon via systemctl because systemctl, gdbus, and busctl commands were not stubbed. The wait_for_avahi_dbus.sh script attempted to query real system services, waiting 20+ seconds before timing out.

**Fix Applied**: Added stubs for systemctl, gdbus, and busctl to both test cases:
- systemctl stub returns "active" for is-active queries and success for start commands
- gdbus and busctl stubs return immediate success (exit 0)
- This allows wait_for_avahi_dbus.sh to complete without needing actual D-Bus infrastructure

**Outage Documented**: `outages/2025-11-05-join-gate-missing-dbus-stubs.json`

**Tests now passing**:
1. ✅ "join gate acquire and release manage publisher state"
2. ✅ "join gate wait retries while lock is present"

### 🔍 discover_flow.bats (status: partial fix attempted)

**Symptoms:**
- Test 5 ("discover flow joins existing server when discovery succeeds") fails
- Tests timeout during execution

**Investigation done (2025-11-05)**:
1. Added gdbus and busctl stubs (similar to join_gate fix)  
2. Added l4_probe stub to avoid network connectivity failures
3. Tests 1-4 pass; test 5 still times out

**Root Cause (partial)**:
- Missing systemd/dbus stubs (fixed)
- Missing l4_probe stub to avoid DNS resolution failures (attempted)
- Additional investigation needed to understand why test 5 still hangs

**Recommended Next Steps**:
1. Run test 5 with full debug output to see where it hangs
2. Check if additional stubs are needed (k3s install, etc.)
3. Consider if DISABLE_JOIN_GATE or other skip flags are needed
4. May need to stub k3s installation process itself

**Estimated Complexity**: Higher than initially assessed - needs dedicated PR

**Tests status**:
- ✅ Tests 1-4: Passing
- ❌ Test 5: Still times out (needs further investigation)
- ⚠️ Tests 6-8: Not yet tested (blocked by test 5)

**Tests to investigate:**
- "discover flow joins existing server when discovery succeeds" (test 5)
- Any subsequent tests

## Recommended Approach (UPDATED 2025-11-05)

### Current Status (Updated 2025-11-05)
- ✅ 15/18 mdns_selfcheck tests passing (was 10/18)
- 🔴 3 tests remaining - Test 8 and Test 15 are complex (2-4 hrs each), Test 16 appears to hang

### Revised Priority Order

#### Phase 1: Investigate Simple Tests First (Est: 1-2 hours)
Tests that may be simpler than the complex 3:
1. Line 254: "strips surrounding quotes before matching" - May just need test fix
2. Line 293: "accepts short host when EXPECTED_HOST has .local" - May need hostname parsing fix  
3. Line 476: "tolerates extra avahi-browse fields and anchors by type" - May need awk pattern fix

Run each test with DEBUG logging to understand actual vs expected behavior.

#### Phase 2: Complex Test Fixes (Est: 8-11 hours total)
Each should be its own focused PR:

1. **Test 8: Resolution Lag Warning** (2-3 hours)
   - Start by investigating why stubbed resolution returns status 2
   - See action plan "Investigation Findings" for detailed analysis
   - Consider creating agent fixtures as reusable test infrastructure
   
2. **Test 15: DBus Fallback Logging** (3-4 hours)
   - Requires implementing dbus preference when SUGARKUBE_MDNS_DBUS=1
   - Alternative: Discuss with maintainer if test expectations should change
   - See action plan for flow restructuring details

3. **Test 16: DBus Wait Logic** (3-4 hours)
   - Implement new gdbus introspect wait function
   - Coordinate with existing busctl wait logic
   - See action plan for implementation approach

### Phase 3: Fix discover_flow.bats and join_gate.bats (Est: 2-4 hours)
1. Run tests with verbose output to see where they hang
2. Add necessary stubs (likely curl and possibly others)
3. Adjust timeouts if needed
4. May require deeper investigation of test logic

## Quick Win Strategy

If time is limited, prioritize this order:
1. ✅ Apply curl stub fix to all 12 server role tests (LOW EFFORT, HIGH IMPACT)
2. Investigate and fix any remaining mdns_selfcheck failures
3. Create separate PR for discover_flow and join_gate timeout issues

## Code Changes Checklist

For each test fix:
- [ ] Add curl stub before the `run env` command
- [ ] Run test individually to verify fix
- [ ] Check for any additional errors
- [ ] Update this document with results

## Files Modified
- `tests/bats/mdns_wire_probe.bats` - ✅ Complete
- `tests/bats/mdns_selfcheck.bats` - 🔄 In Progress (15/18 passing)
- `tests/bats/discover_flow.bats` - 🔄 Partial (tests 1-4 passing, test 5+ need investigation)
- `tests/bats/join_gate.bats` - ✅ Complete (2/2 passing)

## Success Criteria

**Minimum viable (this PR):**
- ✅ mdns_wire_probe.bats: 4/4 passing
- 🎯 mdns_selfcheck.bats: 15+/18 passing
- 📝 Outage documentation for all root causes
- 📝 This document for remaining work

**Stretch goals:**
- mdns_selfcheck.bats: 18/18 passing
- discover_flow.bats: All passing
- join_gate.bats: All passing
- Complete CI green

## Time Estimate (REVISED 2025-11-05)

Based on deep investigation findings:

### Simple Tests (if they exist)
- Lines 254, 293, 476 investigation: **1-2 hours**
- Fixes for simple tests (if any): **30 min - 1 hour each**

### Complex Tests (confirmed high effort)
- Test 8 (Resolution lag warning): **2-3 hours**
- Test 15 (DBus fallback logging): **3-4 hours**  
- Test 16 (DBus wait logic): **3-4 hours**

### Other Test Suites
- discover_flow + join_gate investigation and fixes: **2-4 hours**

**Revised Total for mdns_selfcheck.bats 18/18**: 9-15 hours  
**Total for full CI green**: 11-19 hours

**Key Learning**: Original estimates were 3-5x too optimistic due to:
- Hidden fixture incompatibilities
- Tool/command mismatches in test stubs
- Complex status code semantics in resolution logic
- Need to restructure execution flows, not just add code

**Recommendation**: Each complex test should be its own PR with comprehensive testing.

## Notes

- Python tests are already 100% passing (850 passed, 11 skipped)
- All root causes identified so far have simple, systematic fixes
- No code changes to core scripts needed - only test stubs
- Good test coverage exists, just needs proper mocking

## Investigation Lessons Learned (2025-11-05)

After deep-dive investigation of Tests 8, 15, and 16:

### What Looked Simple But Wasn't

1. **"Add a log line"** often means **"restructure execution flow"**
   - Test 15 requires implementing dbus-first preference, not just logging
   - Need to add new code path before existing browse logic

2. **"Add retry logic"** often means **"implement new wait function with different tool"**
   - Test 16 expects gdbus introspect, but existing code uses busctl
   - Can't just modify existing wait function - need parallel implementation

3. **"Fix test fixture"** can uncover **deeper semantic mismatches**
   - Test 8 fixture role fixed, but revealed status code issues
   - Resolution returns status 2 (ipv4_mismatch) not status 1 (resolve_failed)
   - Code exits early before warning logic can trigger

### Investigation Best Practices

1. **Run test manually with DEBUG first** - Don't trust the test description
2. **Check test fixtures match expectations** - Roles, IPs, service types
3. **Trace full execution path** - Follow code with test stubs to see actual flow
4. **Understand status code semantics** - Exit codes often have specific meanings
5. **Read test setup carefully** - Stubs reveal assumptions about how code should work
6. **Verify stub tools match code** - gdbus vs busctl, avahi-browse vs avahi-resolve
7. **Budget 3-5x initial estimate** - Hidden complexity is the norm, not exception

### Red Flags for Scope Inflation

- Test expects behavior that doesn't exist in current code
- Test fixtures don't match test parameters
- Stubbed commands don't match what code actually calls
- Multiple early exit paths before expected logic
- Status codes with special semantics (not just 0/1)

### Recommended Approach for Complex Tests

1. **One test per PR** - Don't batch complex fixes
2. **Investigate thoroughly first** - Spend time understanding before coding
3. **Test beyond the failing test** - Ensure fix doesn't break other paths
4. **Document complexity** - Update notes with findings for next developer
5. **Consider test intent** - Sometimes test expectations should change vs code

See `ci-test-fixes-action-plan.md` "Investigation Findings (2025-11-05)" section for detailed analysis of each test's complexity.
