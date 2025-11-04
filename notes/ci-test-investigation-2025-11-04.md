# CI Test Failures Investigation Summary

**Date**: 2025-11-04  
**Issue**: Follow-up work after PR #1672 to fix remaining test failures  
**Context**: PR #1672 fixed 14/18 mdns_selfcheck tests plus mdns_wire_probe tests. This continues that work.

## Investigation Findings

### Environment Challenges

Tests behave differently in the sandboxed development environment vs GitHub Actions CI:
- **Local Environment**: Many tests hang indefinitely, particularly mdns_selfcheck tests 1-2
- **CI Environment**: Tests complete but some fail with specific assertion errors

The hanging appears related to:
1. Real `gdbus` and `avahi` commands being called despite stubs
2. Path stubbing not completely isolating test environment  
3. System dbus/avahi services interfering with tests

### Root Cause Categories

#### 1. Active Query Window Logic Issues

**Files**: `scripts/mdns_type_check.sh:167-196`

The active query window logic that handles service type enumeration fallback has issues:

```bash
# Line 173-184: awk processes browse output to count instances
active_count="$(printf '%s\n' "${active_output}" | awk -v svc="${SERVICE_TYPE}" '
BEGIN { FS = ";"; count = 0 }
$1 == "=" {
  for (i = 1; i <= NF; i++) {
    if ($i == svc) {
      count++
      break
    }
  }
}
END { print count }
"' 2>/dev/null | tr -d '\n' | tr -d '\r')"
```

**Problem**: This awk command appears to hang or fail in certain contexts, preventing `active_found` from being set to 1.

**Evidence**:
- Debug logs show `mdns_browse_active` completes successfully with instances in output
- But script exits before logging the count or setting `active_found=1`
- Awk works fine when tested in isolation with same input

**Impact**: Tests expecting the active query to succeed (tests 3, 4) fail because the script exits early with code 4 instead of continuing.

#### 2. Fail-Fast Exit Code Logic

**Files**: `scripts/mdns_type_check.sh:278-305`

When service type is missing from enumeration:
```bash
if [ "${type_present}" -eq 0 ] && [ "${active_found}" -eq 0 ]; then
  # ... logs and exits with code 4
  exit 4
fi
```

**Problem**: The logic is correct but depends on `active_found` being set properly (see issue #1 above).

**Expected Behavior**: 
- If `type_present=0` AND `active_found=1`: Continue to main loop (instances found via active query)
- If `type_present=0` AND `active_found=0`: Exit with code 4 (service type missing)

#### 3. Test-Specific Issues

Each remaining failing test has distinct issues documented in outages/:

**Test 3** (line 158): Service type enumeration warn - needs active query fix
**Test 4** (line 202): Active query window attempts - needs active query fix + logging
**Test 8** (line 381): Resolution lag handling - needs investigation of resolution failure paths
**Test 9** (line 421): Browse empty detection - needs investigation of empty result handling
**Test 10** (line 454): Service type missing exit code - needs active query fix or exit code validation
**Test 12** (line 541): IPv4 mismatch exit code 5 - needs investigation of IP validation logic
**Test 13** (line 585): Bootstrap role filtering - needs investigation of role matching logic
**Test 15** (line 664): DBus fallback logging - needs investigation of fallback logging
**Test 16** (line 722): DBus wait logic - needs investigation of wait_for_avahi_dbus

#### 4. Timeout Issues

**discover_flow.bats** and **join_gate.bats** timeout, likely due to:
- Missing curl stubs for API readiness checks
- Hanging on actual network operations
- Missing other command stubs

## Recommended Next Steps

### Immediate (Quick Wins)

1. **Fix Active Query Awk Hang**
   - Add timeout wrapper around awk command
   - Or replace awk with simpler bash parsing
   - Or add error handling to detect hang and fallback

2. **Add Debug Logging**
   - Add strategic log points around active_count calculation
   - Log `active_found` value before fail-fast check
   - This will help diagnose in CI where tests actually complete

3. **Add Curl Stubs to Remaining Tests**
   - Review tests 3, 4, 8-16 for missing curl stubs
   - Pattern: Same as tests 1, 2, 5-7 that already pass

### Medium Term

4. **Investigate Test-Specific Logic**
   - For each test, trace through expected code path
   - Add necessary stubs, fix assertions, or correct logic
   - Test in CI (not local environment due to hanging)

5. **Fix Timeout Tests**
   - Add curl stubs to discover_flow.bats
   - Add curl stubs to join_gate.bats
   - Review for other missing command stubs

### Long Term

6. **Improve Test Isolation**
   - Ensure PATH stubbing completely overrides system commands
   - Consider mocking dbus entirely rather than relying on system dbus
   - Add test environment validation (check no real avahi commands called)

7. **Add Timeouts to Script Logic**
   - Wrap potentially hanging operations (awk, external commands) in timeouts
   - Use bash `timeout` command or implement timeout logic
   - Fail fast rather than hang indefinitely

## Files to Focus On

- `scripts/mdns_type_check.sh` - Core active query logic
- `scripts/mdns_selfcheck.sh` - Main retry loop, IP validation, role filtering
- `scripts/mdns_resolution.sh` - Resolution failure handling
- `scripts/mdns_selfcheck_dbus.sh` - DBus-specific logic
- `tests/bats/mdns_selfcheck.bats` - Test definitions
- `tests/bats/discover_flow.bats` - Timeout investigation
- `tests/bats/join_gate.bats` - Timeout investigation

## Testing Strategy

Given local environment challenges:

1. **Make minimal, targeted changes**
2. **Add extensive logging** to understand code paths
3. **Test in CI**, not locally (use PR checks)
4. **Iterate quickly** based on CI feedback

## Success Criteria

- All 18 mdns_selfcheck.bats tests passing
- All discover_flow.bats tests passing
- All join_gate.bats tests passing
- CI workflow fully green
- All root causes documented in outages/
