# CI Test Fixes Progress - 2025-11-04

## Summary

Fixed 1 of 8 failing mdns_selfcheck.bats tests by resolving an awk hang issue.  
Identified root causes for remaining 7 tests, but implementations require more complex changes than initially estimated.

## Completed

### Test 3: "warns when enumeration misses but browse succeeds" ✅
- **Root Cause**: Awk command in active query parsing could hang in test contexts
- **Fix Applied**: Replaced awk with pure bash parsing (lines 173-196 of mdns_type_check.sh)
- **Outages Created**:
  - `outages/2025-11-04-mdns-selfcheck-active-query-awk-hang.json`
  - `outages/2025-11-04-mdns-selfcheck-test-03-enum-warn.json`
- **Test Status**: PASSING ✅

## In Progress / Blocked

### Test 4: "waits for active queries when instance appears within window"
- **Status**: FAILING (not timing out)
- **Expected**: `attempts=3` in output
- **Issue**: Main loop retry logic - unrelated to awk fix
- **Complexity**: Medium - needs investigation of main retry loop

### Test 8: "warns when browse succeeds but resolution lags"
- **Status**: FAILING (not timing out)
- **Expected**: Exit code 0, outcome=warn, reason=resolve_failed  
- **Issue**: Needs conditional exit logic when browse succeeds but resolution fails
- **Complexity**: Medium - requires new code path in mdns_selfcheck.sh

### Test 9: "reports failure when no records appear"
- **Status**: FAILING (not timing out)
- **Expected**: reason=browse_empty in output
- **Issue**: Final failure logging doesn't include specific reason
- **Complexity**: Low - just needs better reason tracking

### Test 10: "fails fast when service type is missing"
- **Status**: FAILING (not timing out)
- **Expected**: Exit code 4, event=mdns_type_check on stderr
- **Issue**: Log routing - mdns_type_check warning goes to stdout but test expects stderr
- **Complexity**: High - requires understanding of when diagnostics go to stderr vs stdout
- **Notes**: 
  - Test 3 expects same log on stdout (and passes)
  - Test 10 expects same log on stderr (and fails)
  - Need dual logging or conditional routing based on whether we're exiting with error

### Test 12: "returns distinct code on IPv4 mismatch"
- **Status**: TIMING OUT ⏱️
- **Expected**: Exit code 5, outcome=fail, reason=ipv4_mismatch
- **Issue**: Needs IPv4 validation logic with special exit code
- **Complexity**: Medium - new validation code path

### Test 13: "ignores bootstrap advertisement when server required"
- **Status**: FAILING (not timing out)
- **Expected**: Exit code 1, reason=instance_not_found
- **Issue**: Needs role filtering in main loop
- **Complexity**: Medium - parse and filter by TXT record role

### Test 15: "falls back to CLI when dbus browser creation fails"
- **Status**: TIMING OUT ⏱️
- **Expected**: Exit code 0, fallback=cli in output
- **Issue**: Missing fallback logging
- **Complexity**: Low - just add log statement

### Test 16: "dbus self-check waits for avahi bus before browsing"
- **Status**: TIMING OUT ⏱️
- **Expected**: Exit code 0, event=avahi_dbus_ready
- **Issue**: Needs wait/retry loop for dbus service availability
- **Complexity**: High - new retry logic with ServiceUnknown error detection

## Timeouts vs Failures

After awk fix:
- **Not timing out** (failing but completing): Tests 4, 8, 9, 10, 13  
- **Timing out**: Tests 12, 15, 16
- **Passing**: Test 3 (and tests 1, 2, 5, 6, 7, 11, 14 from previous fixes)

The awk fix may have helped tests complete faster, but timeouts in 12, 15, 16 suggest additional blocking issues.

## Recommendations for Next Steps

1. **Test 9** (browse_empty) - Lowest complexity, quick win
2. **Test 4** (attempts logging) - Investigate main loop to understand why attempts not logged  
3. **Test 13** (role filtering) - Add TXT record role parsing and filtering
4. **Test 8** (resolution lag warning) - Add conditional success path when browse works but resolve fails
5. **Test 15** (dbus fallback logging) - Just add log statement
6. **Test 10** (stderr routing) - Complex stdout/stderr routing issue, needs design decision
7. **Test 12** (IPv4 mismatch) - Debug timeout, then add validation logic
8. **Test 16** (dbus wait) - Complex retry logic, investigate timeout first

## Lessons Learned

1. **Stdout/stderr routing is complex**: Tests have different expectations for same log messages
2. **Timeouts may indicate missing stubs**: Tests 12, 15, 16 timing out likely need curl/dbus stubs
3. **Pure bash > awk in tests**: Awk can hang unpredictably in test command substitution contexts
4. **Each test fix needs careful analysis**: Simple-looking fixes can have hidden complexity

## Time Estimate for Remaining Work

- Tests 9, 15: 30 minutes each (low complexity)
- Tests 4, 8, 13: 1-2 hours each (medium complexity, needs investigation)
- Tests 10, 16: 2-3 hours each (high complexity, design decisions needed)
- Test 12: 1 hour (timeout debug + logic)

**Total**: 8-15 hours for all remaining mdns_selfcheck tests

Plus:
- discover_flow.bats: 2-4 hours
- join_gate.bats: 2-4 hours

**Grand Total**: 12-23 hours for complete CI green

## Update: Additional Investigation

### Test 9 Attempted Fix

Attempted to add `reason=browse_empty` by setting `last_reason="browse_empty"` when miss_count >= ATTEMPTS and last_reason is empty. However, discovered that:

1. The script has multiple exit points within the main loop (lines 507, 577, 612, 626, 644, 671, 697, 733)
2. When browse is truly empty, the script may be exiting via one of these earlier paths
3. The final failure logging section (line 855+) may not be reached in all failure scenarios
4. Need deeper investigation of control flow to understand which exit path is taken when browse returns no records

**Recommendation**: Test 9 requires more detailed flow analysis to identify which exit path is used for browse_empty scenario, then add appropriate reason logging at that exit point.

## Summary

Successfully fixed 1 of 8 failing mdns_selfcheck tests (Test 3). Remaining tests require deeper code analysis and architectural decisions (especially around stdout/stderr routing). Each test is more complex than initially estimated.

**Time Invested**: ~3 hours  
**Tests Fixed**: 1 (Test 3)  
**Outages Documented**: 2  
**Progress Documentation**: Complete analysis of all remaining failures

**Next Steps** for future PRs:
1. Map all exit paths in mdns_selfcheck.sh main loop
2. Identify which path is taken for each test scenario
3. Add appropriate reason/logging at each relevant exit point
4. Consider refactoring to simplify control flow
