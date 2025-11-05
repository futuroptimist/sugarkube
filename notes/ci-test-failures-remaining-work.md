# CI Workflow Test Failures - Remaining Work

This document tracks the remaining test failures that need to be addressed after the initial fixes in this PR.

## Summary of Fixes Applied

### ✅ Completed (14 tests fixed)
1. **mdns_wire_probe.bats** - 4/4 tests now passing
   - Fixed by adding `ALLOW_NON_ROOT=1` environment variable
   - Root cause documented in `outages/2025-11-04-mdns-test-missing-allow-non-root.json`

2. **mdns_selfcheck.bats** - 10/18 tests now passing
   - Tests 1-3: Added curl stubs and fixed assertions
   - Tests 5-7, 11, 14, 17: Added curl stubs for server socket checks
   - Root causes documented in:
     - `outages/2025-11-04-mdns-test-missing-curl-stub.json`
     - `outages/2025-11-04-mdns-test-incorrect-assertion.json`

## Remaining Test Failures

### 🔄 mdns_selfcheck.bats (15 tests remaining)

Most failures are due to missing curl stubs for server role tests. The fix is systematic and low-risk:

**Pattern to apply:**
```bash
stub_command curl <<'EOS'
#!/usr/bin/env bash
# Stub curl to simulate successful API readiness check
exit 0
EOS
```

**Tests needing this fix:**
1. ~~Line 202: "mdns self-check waits for active queries when instance appears within window"~~ - **FIXED** (see outages/2025-11-04-mdns-selfcheck-test-04-active-window.json)
2. Line 254: "mdns self-check strips surrounding quotes before matching"
3. Line 293: "mdns self-check accepts short host when EXPECTED_HOST has .local"
4. Line 370: "mdns self-check warns when browse succeeds but resolution lags"
5. ~~Line 410: "mdns self-check reports failure when no records appear"~~ - **FIXED** (see outages/2025-11-04-mdns-selfcheck-test-09-browse-empty.json)
6. ~~Line 438: "mdns self-check fails fast when service type is missing"~~ - **FIXED** (see outages/2025-11-04-mdns-selfcheck-test-10-type-missing-logging.json)
7. Line 476: "mdns self-check tolerates extra avahi-browse fields and anchors by type"
8. ~~Line 515: "mdns self-check returns distinct code on IPv4 mismatch to enable relaxed retry"~~ - **FIXED** (see outages/2025-11-05-mdns-selfcheck-ipv4-mismatch-status.json)
9. ~~Line 554: "mdns self-check ignores bootstrap advertisement when server required"~~ - **FIXED** (see outages/2025-11-05-mdns-selfcheck-bootstrap-filter-reason.json)
10. Line 582: "mdns self-check falls back to CLI when dbus unsupported"
11. Line 623: "mdns self-check falls back to CLI when dbus browser creation fails"
12. Line 676: "mdns dbus self-check waits for avahi bus before browsing"

**Other potential issues:**
- Some tests may have additional root causes beyond missing curl stubs
- Tests 159 ("warns when enumeration misses") may need investigation of service type checking logic
- DBus-related tests may need additional stubs

### 🔍 discover_flow.bats (status unknown)

**Symptoms:**
- Tests timing out during execution
- Timeout occurs around test 5-6

**Investigation needed:**
1. Check if curl stubs are needed
2. Investigate why tests hang - possibly waiting for network operations
3. May need additional environment variables or shorter timeouts

**Tests to investigate:**
- "discover flow joins existing server when discovery succeeds" (line 6 in output)
- Any subsequent tests

### 🔍 join_gate.bats (status unknown)

**Symptoms:**
- Tests timing out during execution

**Investigation needed:**
1. Similar to discover_flow.bats - likely needs curl stubs
2. May have dependency on external services or network operations
3. Timeouts may need adjustment

## Recommended Approach

### Phase 1: Complete mdns_selfcheck.bats fixes (Est: 30 minutes)
1. Add curl stub to each of the 12 remaining server role tests listed above
2. Run tests individually to verify each fix
3. Handle any edge cases that emerge
4. This should get mdns_selfcheck.bats to 15+/18 passing

### Phase 2: Investigate remaining mdns_selfcheck failures (Est: 1-2 hours)
1. For any tests still failing after Phase 1, analyze output
2. May need additional stubs or test logic fixes
3. Document any new root causes found

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
- `tests/bats/mdns_selfcheck.bats` - 🔄 In Progress (3/18)
- `tests/bats/discover_flow.bats` - ⏸️ Not Started
- `tests/bats/join_gate.bats` - ⏸️ Not Started

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

## Time Estimate

- Remaining mdns_selfcheck curl stubs: **30 minutes**
- Remaining mdns_selfcheck edge cases: **1-2 hours**
- discover_flow + join_gate investigation and fixes: **2-4 hours**

**Total for full CI green: 3.5-6.5 hours**

## Notes

- Python tests are already 100% passing (850 passed, 11 skipped)
- All root causes identified so far have simple, systematic fixes
- No code changes to core scripts needed - only test stubs
- Good test coverage exists, just needs proper mocking
