# Test Numbering Standardization (2025-11-09)

## Problem

An off-by-one numbering discrepancy was discovered in documentation and outage files for discover_flow.bats tests. Two different numbering systems were being used inconsistently:

**Old System** (used in notes/ci-test-failures-remaining-work.md from 2025-11-05):
- Test 6 = "joins existing server" 
- Test 7 = "elects winner"
- Test 8 = "remains follower"

**New System** (used in 2025-11-09 outages):  
- Test 5 = "joins existing server"
- Test 6 = "elects winner"
- Test 7 = "remains follower"

This caused confusion where outage file `2025-11-09-test7-discover-flow-election-fix.json` actually documents Test 6 ("discover flow elects winner after self-check failure"), not Test 7.

## Authoritative Mapping

Based on position of `@test` declarations in `tests/bats/discover_flow.bats`:

| Position | Line | Test Name | Status |
|----------|------|-----------|--------|
| Test 1 | 285 | "wait_for_avahi_dbus reports ready when Avahi registers quickly" | ✅ Passing |
| Test 2 | 322 | "wait_for_avahi_dbus exits with disabled when enable-dbus=no" | ✅ Passing |
| Test 3 | 348 | "wait_for_avahi_dbus logs timeout details when Avahi is absent" | ✅ Passing |
| Test 4 | 386 | "discover flow waits for Avahi liveness after reload" | ✅ Passing |
| **Test 5** | **513** | **"discover flow joins existing server when discovery succeeds"** | ✅ FIXED 2025-11-09 |
| **Test 6** | **646** | **"discover flow elects winner after self-check failure"** | ✅ FIXED 2025-11-09 |
| **Test 7** | **788** | **"discover flow remains follower after self-check failure"** | ✅ FIXED 2025-11-09 |
| Test 8 | 834 | "run_k3s_install uses stub when SUGARKUBE_K3S_INSTALL_SCRIPT is set" | ✅ Passing |
| Test 9 | 863 | "Avahi check warns on IPv4 suffix and can auto-fix" | ✅ Passing |

## Standard Going Forward

**Use position-based numbering** (Test 1-9 as shown above) consistently across all documentation.

**When referencing tests, always include**:
1. Position number (Test 5, Test 6, Test 7)
2. Line number (line 513, line 646, line 788)
3. Full quoted test name

**Example**: Test 7 "discover flow remains follower after self-check failure" (line 788)

## Files Corrected in This PR

- `notes/ci-test-failures-remaining-work.md` - Fixed line numbers and test numbers
- `notes/skipped-tests-status.md` - Already correct, confirmed accuracy
- `notes/test-suite-xy-analysis-20251108.md` - Checked for consistency
- This file created to document the standardization

## Outage File Naming

The file `outages/2025-11-09-test7-discover-flow-election-fix.json` is **incorrectly named**:
- It documents Test 6 "elects winner" (line 646)
- Should be named `test6` not `test7`

**Decision**: Leave filename as-is to preserve git history, but document the error in this file. The JSON content correctly identifies it as Test 6.

## Lessons Learned

1. **Always use full test names**: Avoid relying solely on numbers which can be ambiguous
2. **Include line numbers**: Makes it unambiguous which test is referenced
3. **Standardize early**: Define numbering system at start of project
4. **Cross-reference carefully**: When copying/updating notes, verify test identities

## Recommendation

Future work should reference tests using this pattern:
```
Test 7 "discover flow remains follower after self-check failure" (line 788)
```

This format includes:
- Position (Test 7)
- Full name in quotes
- Line number for verification
