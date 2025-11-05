# Action Plan: Fix Remaining CI Test Failures

**Date**: 2025-11-04  
**Context**: Follow-up to PR #1672 which fixed 14/18 mdns_selfcheck tests  
**Goal**: Provide exact, step-by-step instructions to fix all remaining test failures

## Overview

This document provides precise implementation instructions for fixing the 8 remaining mdns_selfcheck.bats test failures plus discover_flow.bats and join_gate.bats timeout issues. Each fix includes:
- Exact file location and line number
- Complete code to add
- Expected test behavior after fix
- Outage JSON to create with the fix

## Test Failures Summary

### mdns_selfcheck.bats: 8 tests failing
- Test 3 (line 158): Service type enumeration warning
- Test 4 (line 202): Active query window retry attempts
- Test 8 (line 381): Resolution lag warning
- Test 9 (line 421): Browse empty failure reporting
- Test 10 (line 454): Service type missing exit code 4
- Test 12 (line 541): IPv4 mismatch exit code 5
- Test 13 (line 585): Bootstrap role filtering
- Test 15 (line 664): DBus→CLI fallback logging
- Test 16 (line 722): DBus wait/retry logic

### Other test files: 2 files timing out
- discover_flow.bats: Tests hang around test 5-6
- join_gate.bats: Test 1 hangs

---

## PRIORITY 1: Core Issue - Active Query Awk Hang

**Root Cause**: The awk command in `scripts/mdns_type_check.sh:173-184` appears to hang in certain test execution contexts, preventing `active_found` from being set to 1.

### Fix Location
**File**: `scripts/mdns_type_check.sh`  
**Lines**: 173-184

### Current Code
```bash
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

### Recommended Fix: Add Timeout Wrapper
Replace the awk with a timeout-wrapped version or pure bash parsing. Option 1 (preferred):

```bash
# Add timeout to prevent hangs - use timeout command if available
if command -v timeout >/dev/null 2>&1; then
  active_count="$(printf '%s\n' "${active_output}" | timeout 5 awk -v svc="${SERVICE_TYPE}" '
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
' 2>/dev/null | tr -d '\n' | tr -d '\r')"
else
  # Fallback to pure bash if timeout not available
  active_count=0
  while IFS= read -r line; do
    if [[ "${line}" =~ ^=\;.*\;${SERVICE_TYPE}\; ]]; then
      ((active_count++))
    fi
  done <<< "${active_output}"
fi
```

### Alternative Fix: Pure Bash Parsing
Replace awk entirely with bash:

```bash
# Count service instances using pure bash (more robust than awk in test contexts)
active_count=0
if [ -n "${active_output}" ]; then
  local old_ifs="${IFS}"
  while IFS= read -r browse_line; do
    [ -n "${browse_line}" ] || continue
    IFS=';'
    set -- ${browse_line}
    IFS="${old_ifs}"
    if [ "$1" = "=" ]; then
      for field in "$@"; do
        if [ "${field}" = "${SERVICE_TYPE}" ]; then
          active_count=$((active_count + 1))
          break
        fi
      done
    fi
  done <<< "${active_output}"
  IFS="${old_ifs}"
fi
```

### Outage to Create After Fix
**File**: `outages/2025-11-04-mdns-selfcheck-active-query-awk-hang.json`

```json
{
  "id": "2025-11-04-mdns-selfcheck-active-query-awk-hang",
  "date": "2025-11-04",
  "component": "scripts/mdns_type_check.sh:173-184",
  "rootCause": "Active query awk processing could hang in certain test execution contexts when counting service instances. The awk command parsing avahi-browse output would not complete, preventing active_found from being set and causing premature exit with code 4.",
  "resolution": "Replaced awk with timeout-wrapped version or pure bash parsing using pattern matching and field iteration. The bash implementation is more robust in test environments where awk may interact unpredictably with command substitution and heredocs.",
  "references": [
    "tests/bats/mdns_selfcheck.bats:158-252",
    "scripts/mdns_type_check.sh:167-196"
  ]
}
```

### Tests Fixed by This Change
- Test 3: "mdns self-check warns when enumeration misses but browse succeeds"
- Test 4: "mdns self-check waits for active queries when instance appears within window"
- Test 10: "mdns self-check fails fast when service type is missing"

---

## TEST 3: Service Type Enumeration Warning

**Test**: `tests/bats/mdns_selfcheck.bats:158-200`  
**Name**: "mdns self-check warns when enumeration misses but browse succeeds"

### Current Status
- EXPECTED: Exit code 0, outcome=ok, severity=warn for type check
- ACTUAL: Exit code 4 (service_type_missing)

### Root Cause
Service type is missing from enumeration (_services._dns-sd._udp) but instances ARE found via active query. Script should warn but continue, not fail.

### Fix Required
**PRIMARY**: Fix the awk hang issue (see PRIORITY 1 above)  
**SECONDARY**: Ensure no additional issues after awk fix

### Verification After Fix
```bash
cd /home/runner/work/sugarkube/sugarkube
export BATS_LIB_PATH="${PWD}/tests/bats"
bats -f "mdns self-check warns when enumeration misses" tests/bats/mdns_selfcheck.bats
```

Should output:
```
ok 1 mdns self-check warns when enumeration misses but browse succeeds
```

### Outage to Create After Fix
**File**: `outages/2025-11-04-mdns-selfcheck-test-03-enum-warn.json`

```json
{
  "id": "2025-11-04-mdns-selfcheck-test-03-enum-warn",
  "date": "2025-11-04",
  "component": "tests/bats/mdns_selfcheck.bats:158",
  "rootCause": "Test failed because active query awk hang prevented active_found=1 from being set. When service type missing from enumeration but instances found via active browse, script should warn (severity=warn) and continue (exit 0), but instead exited early with code 4 due to active_found=0.",
  "resolution": "Fixed by resolving awk hang issue in mdns_type_check.sh:173-184. Active query now properly sets active_found=1 when instances discovered, allowing script to continue to main loop despite type_present=0.",
  "references": [
    "tests/bats/mdns_selfcheck.bats:158-200",
    "scripts/mdns_type_check.sh:167-196",
    "outages/2025-11-04-mdns-selfcheck-active-query-awk-hang.json"
  ]
}
```

---

## TEST 4: Active Query Window Retry Attempts

**Test**: `tests/bats/mdns_selfcheck.bats:202-252`  
**Name**: "mdns self-check waits for active queries when instance appears within window"

### Current Status
- EXPECTED: Output contains `attempts=3`
- ACTUAL: Output missing `attempts=3`

### Root Cause
Active query retry loop increments `active_attempts` but may not be logging it properly when instances found on 3rd attempt.

### Fix Required
**PRIMARY**: Fix the awk hang issue (see PRIORITY 1 above)  
**SECONDARY**: Verify logging at line 195

Check that this log line exists and is reached:
```bash
log_debug mdns_selfcheck event=mdns_type_active outcome=hit attempts="${active_attempts}" instances="${active_count}"
```

### Additional Debug Logging (if needed)
Add before line 195 to ensure we're reaching the success path:

```bash
if [ "${active_count}" -gt 0 ]; then
  # Log before setting variables to debug
  log_debug mdns_selfcheck event=active_query_success count="${active_count}" attempt="${active_attempts}"
  
  # shellcheck disable=SC2034  # Used in sourcing script (mdns_selfcheck.sh)
  INITIAL_BROWSE_OUTPUT="${active_output}"
  # ... rest of existing code
```

### Verification After Fix
```bash
export BATS_LIB_PATH="${PWD}/tests/bats"
bats -f "waits for active queries when instance appears" tests/bats/mdns_selfcheck.bats
```

Should output:
```
ok 1 mdns self-check waits for active queries when instance appears within window
```

### Outage to Create After Fix
**File**: `outages/2025-11-04-mdns-selfcheck-test-04-active-window.json`

```json
{
  "id": "2025-11-04-mdns-selfcheck-test-04-active-window",
  "date": "2025-11-04",
  "component": "tests/bats/mdns_selfcheck.bats:202",
  "rootCause": "Test expected 'attempts=3' in output when active query succeeds on 3rd retry attempt. The active query window logic was not reaching the success logging due to awk hang preventing loop completion.",
  "resolution": "Fixed by resolving awk hang in mdns_type_check.sh:173-184. Active query loop now completes properly and logs attempts count when instances are discovered (line 195).",
  "references": [
    "tests/bats/mdns_selfcheck.bats:202-252",
    "scripts/mdns_type_check.sh:168-196",
    "outages/2025-11-04-mdns-selfcheck-active-query-awk-hang.json"
  ]
}
```

---

## TEST 8: Resolution Lag Warning

**Test**: `tests/bats/mdns_selfcheck.bats:381-419`  
**Name**: "mdns self-check warns when browse succeeds but resolution lags"

### Current Status
- EXPECTED: Exit code 0, outcome=warn, reason=resolve_failed
- ACTUAL: Non-zero exit code

### Root Cause
When browse finds instance but all resolution methods fail (avahi-resolve, avahi-resolve-host-name, getent all exit with errors), script should return success with warning, not failure.

### Fix Required
**File**: `scripts/mdns_selfcheck.sh`  
**Location**: Main retry loop, after resolution attempts (around lines 550-700)

Find the section where resolution is attempted and check exit code logic. The script should:
1. Attempt resolution via multiple methods
2. If all fail but browse succeeded, log warning and exit 0
3. Not treat resolution failure as fatal error

### Code Pattern to Look For
Search for where resolution status is checked and final exit code determined:

```bash
# Around line 650-700, look for resolution failure handling
if [ "${SELF_RESOLVE_STATUS}" -ne 0 ]; then
  # This section needs to check if browse succeeded
  # If browse found instance, should warn but not fail
```

### Fix to Apply
After resolution attempts fail, before final exit, add:

```bash
# If browse succeeded but resolution failed, warn but don't fail
if [ "${MDNS_RESOLUTION_STATUS_BROWSE}" -eq 1 ] && [ "${SELF_RESOLVE_STATUS}" -ne 0 ]; then
  elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
  log_info mdns_selfcheck outcome=warn reason=resolve_failed host="${srv_host}" ms_elapsed="${elapsed_ms}"
  exit 0
fi
```

### Verification After Fix
```bash
export BATS_LIB_PATH="${PWD}/tests/bats"
bats -f "warns when browse succeeds but resolution lags" tests/bats/mdns_selfcheck.bats
```

### Outage to Create After Fix
**File**: `outages/2025-11-04-mdns-selfcheck-test-08-resolution-lag.json`

```json
{
  "id": "2025-11-04-mdns-selfcheck-test-08-resolution-lag",
  "date": "2025-11-04",
  "component": "tests/bats/mdns_selfcheck.bats:381",
  "rootCause": "When avahi-browse finds service instance but all resolution methods fail (avahi-resolve, avahi-resolve-host-name, getent), script exited with failure instead of warning. Resolution lag is a common transient condition that should not block startup.",
  "resolution": "Added check in mdns_selfcheck.sh main loop to detect when browse succeeds (MDNS_RESOLUTION_STATUS_BROWSE=1) but resolution fails. In this case, script now logs outcome=warn reason=resolve_failed and exits 0 instead of failing.",
  "references": [
    "tests/bats/mdns_selfcheck.bats:381-419",
    "scripts/mdns_selfcheck.sh:650-700",
    "scripts/mdns_resolution.sh"
  ]
}
```

---

## TEST 9: Browse Empty Failure Reporting

**Test**: `tests/bats/mdns_selfcheck.bats:421-452`  
**Name**: "mdns self-check reports failure when no records appear"

### Current Status
- EXPECTED: Exit code 1, outcome=fail, reason=browse_empty
- ACTUAL: Missing `reason=browse_empty` in output

### Root Cause
When browse returns no records after all retry attempts, the final failure logging doesn't include the specific `browse_empty` reason.

### Fix Required
**File**: `scripts/mdns_selfcheck.sh`  
**Location**: End of retry loop, final failure handling (around lines 800-900)

### Code to Find
Look for the final failure case after all attempts exhausted:

```bash
# After retry loop completes without success
if [ "${attempt}" -gt "${ATTEMPTS}" ]; then
  # Final failure logging
```

### Fix to Apply
Ensure the failure logging includes reason based on what was tried:

```bash
# Determine failure reason
final_reason="${last_reason:-unknown}"
if [ -z "${parsed}" ] && [ "${miss_count}" -ge "${ATTEMPTS}" ]; then
  final_reason="browse_empty"
fi

elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
log_info mdns_selfcheck outcome=fail reason="${final_reason}" ms_elapsed="${elapsed_ms}"
exit 1
```

### Verification After Fix
```bash
export BATS_LIB_PATH="${PWD}/tests/bats"
bats -f "reports failure when no records appear" tests/bats/mdns_selfcheck.bats
```

### Outage to Create After Fix
**File**: `outages/2025-11-04-mdns-selfcheck-test-09-browse-empty.json`

```json
{
  "id": "2025-11-04-mdns-selfcheck-test-09-browse-empty",
  "date": "2025-11-04",
  "component": "tests/bats/mdns_selfcheck.bats:421",
  "rootCause": "When avahi-browse returns no service records after all retry attempts, final failure logging did not include reason=browse_empty. The script tracked miss_count but didn't use it to set specific failure reason in final log message.",
  "resolution": "Updated final failure handling in mdns_selfcheck.sh to detect browse_empty condition (no parsed records after all attempts) and log reason=browse_empty specifically. This helps diagnose whether service is truly missing vs other failure modes.",
  "references": [
    "tests/bats/mdns_selfcheck.bats:421-452",
    "tests/fixtures/avahi_browse_empty.txt",
    "scripts/mdns_selfcheck.sh:800-900"
  ]
}
```

---

## TEST 10: Service Type Missing Exit Code 4

**Test**: `tests/bats/mdns_selfcheck.bats:454-495`  
**Name**: "mdns self-check fails fast when service type is missing"

### Current Status
- EXPECTED: Exit code 4, reason=service_type_missing
- ACTUAL: Different exit code

### Root Cause
When service type completely missing (not in _services._dns-sd._udp enumeration AND no instances found via active query), should exit with code 4. Currently may be exiting with different code or hanging.

### Fix Required
**PRIMARY**: Fix the awk hang issue (see PRIORITY 1 above)  
**SECONDARY**: Verify exit code 4 logic in mdns_type_check.sh:281-305

### Code to Verify
Ensure this code block is correct and reachable:

```bash
# scripts/mdns_type_check.sh lines 281-305
if [ "${type_present}" -eq 0 ] && [ "${active_found}" -eq 0 ]; then
  elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
  case "${elapsed_ms}" in
    ''|*[!0-9]*) elapsed_ms=0 ;;
  esac
  
  # ... logging code ...
  log_info mdns_selfcheck outcome=fail reason=service_type_missing service_type="${SERVICE_TYPE}" ms_elapsed="${elapsed_ms}" "${available_kv}"
  exit 4
fi
```

### Verification After Fix
```bash
export BATS_LIB_PATH="${PWD}/tests/bats"
bats -f "fails fast when service type is missing" tests/bats/mdns_selfcheck.bats
```

### Outage to Create After Fix
**File**: `outages/2025-11-04-mdns-selfcheck-test-10-type-missing-exit.json`

```json
{
  "id": "2025-11-04-mdns-selfcheck-test-10-type-missing-exit",
  "date": "2025-11-04",
  "component": "tests/bats/mdns_selfcheck.bats:454",
  "rootCause": "Test expected exit code 4 when service type completely missing from both enumeration and active query, but script was not reaching the fail-fast exit due to awk hang preventing active_found from being properly set to 0.",
  "resolution": "Fixed by resolving awk hang in mdns_type_check.sh:173-184. Active query now completes, active_found is correctly set to 0 when no instances found, and fail-fast logic at line 281-305 properly exits with code 4.",
  "references": [
    "tests/bats/mdns_selfcheck.bats:454-495",
    "scripts/mdns_type_check.sh:278-305",
    "outages/2025-11-04-mdns-selfcheck-active-query-awk-hang.json"
  ]
}
```

---

## TEST 12: IPv4 Mismatch Exit Code 5

**Test**: `tests/bats/mdns_selfcheck.bats:541-583`  
**Name**: "mdns self-check returns distinct code on IPv4 mismatch to enable relaxed retry"

### Current Status
- EXPECTED: Exit code 5, outcome=fail, reason=ipv4_mismatch
- ACTUAL: Different exit code

### Root Cause
When discovered IPv4 (10.0.0.5) doesn't match EXPECTED_IPV4 (10.0.0.99), script should exit with code 5 to allow caller to distinguish from other failures and retry with relaxed IP matching.

### Fix Required
**File**: `scripts/mdns_selfcheck.sh`  
**Location**: IPv4 validation after resolution (around lines 600-700)

### Code to Find
Look for where IPv4 is validated against EXPECTED_IPV4:

```bash
# After successful resolution
if [ -n "${EXPECTED_IPV4}" ] && [ "${resolved_ipv4}" != "${EXPECTED_IPV4}" ]; then
  # IPv4 mismatch handling
```

### Fix to Apply
Ensure IPv4 mismatch exits with code 5:

```bash
# IPv4 validation after resolution
if [ -n "${EXPECTED_IPV4}" ] && [ -n "${resolved_ipv4}" ]; then
  if [ "${resolved_ipv4}" != "${EXPECTED_IPV4}" ]; then
    elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
    log_info mdns_selfcheck outcome=fail reason=ipv4_mismatch \
      expected="${EXPECTED_IPV4}" actual="${resolved_ipv4}" \
      host="${srv_host}" ms_elapsed="${elapsed_ms}"
    exit 5
  fi
fi
```

### Verification After Fix
```bash
export BATS_LIB_PATH="${PWD}/tests/bats"
bats -f "returns distinct code on IPv4 mismatch" tests/bats/mdns_selfcheck.bats
```

### Outage to Create After Fix
**File**: `outages/2025-11-04-mdns-selfcheck-test-12-ipv4-mismatch.json`

```json
{
  "id": "2025-11-04-mdns-selfcheck-test-12-ipv4-mismatch",
  "date": "2025-11-04",
  "component": "tests/bats/mdns_selfcheck.bats:541",
  "rootCause": "When discovered IPv4 address doesn't match EXPECTED_IPV4, script was not exiting with distinct code 5. Exit code 5 allows callers to distinguish IP mismatch (which may be transient during DHCP changes) from other permanent failures and retry with relaxed matching.",
  "resolution": "Added explicit IPv4 validation after resolution in mdns_selfcheck.sh. When resolved IP doesn't match expected, now logs outcome=fail reason=ipv4_mismatch and exits with code 5.",
  "references": [
    "tests/bats/mdns_selfcheck.bats:541-583",
    "scripts/mdns_selfcheck.sh:600-700"
  ]
}
```

---

## TEST 13: Bootstrap Role Filtering

**Test**: `tests/bats/mdns_selfcheck.bats:585-616`  
**Name**: "mdns self-check ignores bootstrap advertisement when server required"

### Current Status
- EXPECTED: Exit code 1, reason=instance_not_found
- ACTUAL: Missing `instance_not_found` in output

### Root Cause
When EXPECTED_ROLE=server but discovered instance has role=bootstrap, script should filter out the bootstrap instance and report no matching instance found.

### Fix Required
**File**: `scripts/mdns_selfcheck.sh`  
**Location**: Role matching logic in main loop (around lines 530-600)

### Code to Find
Look for TXT record parsing and role extraction:

```bash
# Parse TXT records for role
parse_browse() {
  # ... extracts role from txt=role=XXX
}
```

### Fix to Apply
After parsing role from TXT records, add filtering:

```bash
# Extract role from parsed TXT records
discovered_role="${parsed_role:-}"

# Filter by expected role if specified
if [ -n "${EXPECTED_ROLE}" ] && [ -n "${discovered_role}" ]; then
  if [ "${discovered_role}" != "${EXPECTED_ROLE}" ]; then
    log_debug mdns_selfcheck_role_filter \
      expected="${EXPECTED_ROLE}" \
      discovered="${discovered_role}" \
      outcome=skip
    # Skip to next attempt
    continue
  fi
fi
```

### Verification After Fix
```bash
export BATS_LIB_PATH="${PWD}/tests/bats"
bats -f "ignores bootstrap advertisement when server required" tests/bats/mdns_selfcheck.bats
```

### Outage to Create After Fix
**File**: `outages/2025-11-04-mdns-selfcheck-test-13-bootstrap-filter.json`

```json
{
  "id": "2025-11-04-mdns-selfcheck-test-13-bootstrap-filter",
  "date": "2025-11-04",
  "component": "tests/bats/mdns_selfcheck.bats:585",
  "rootCause": "When EXPECTED_ROLE=server but discovered instance advertised role=bootstrap, script was not filtering out the non-matching role. Bootstrap advertisements should be ignored when looking for specific server role, as they represent transient bootstrap state.",
  "resolution": "Added role filtering logic in mdns_selfcheck.sh main loop after TXT record parsing. When discovered role doesn't match EXPECTED_ROLE, instance is skipped. When no matching instances found after all attempts, logs reason=instance_not_found.",
  "references": [
    "tests/bats/mdns_selfcheck.bats:585-616",
    "tests/fixtures/avahi_browse_bootstrap_only.txt",
    "scripts/mdns_selfcheck.sh:530-700"
  ]
}
```

---

## TEST 15: DBus→CLI Fallback Logging

**Test**: `tests/bats/mdns_selfcheck.bats:664-720`  
**Name**: "mdns self-check falls back to CLI when dbus browser creation fails"

### Current Status
- EXPECTED: Exit code 0, outcome=ok, fallback=cli in output
- ACTUAL: Test succeeds but missing `fallback=cli` log

### Root Cause
When SUGARKUBE_MDNS_DBUS=1 but gdbus ServiceBrowserNew fails, script correctly falls back to CLI mode (avahi-browse) and succeeds, but doesn't log the fallback event.

### Fix Required
**File**: `scripts/mdns_selfcheck.sh`  
**Location**: mdns_cli_dbus_fallback function (around line 500-510)

### Code to Find
```bash
mdns_cli_dbus_fallback() {
  # Handles fallback from dbus to CLI mode
```

### Fix to Apply
Add logging when fallback is triggered:

```bash
mdns_cli_dbus_fallback() {
  local browse_rc="$1"
  local attempt="$2"
  
  # Check if dbus mode enabled and browser creation failed
  if [ "${SUGARKUBE_MDNS_DBUS:-0}" -eq 1 ] && [ "${browse_rc}" -ne 0 ]; then
    if [ "${DBUS_CLI_FALLBACK_ENABLED}" -eq 0 ]; then
      DBUS_CLI_FALLBACK_ENABLED=1
      log_info mdns_selfcheck event=dbus_fallback fallback=cli reason=browser_create_failed attempt="${attempt}"
    fi
    DBUS_CLI_FALLBACK_ATTEMPTS=$((DBUS_CLI_FALLBACK_ATTEMPTS + 1))
    return 0
  fi
  return 1
}
```

### Verification After Fix
```bash
export BATS_LIB_PATH="${PWD}/tests/bats"
bats -f "falls back to CLI when dbus browser creation fails" tests/bats/mdns_selfcheck.bats
```

### Outage to Create After Fix
**File**: `outages/2025-11-04-mdns-selfcheck-test-15-dbus-fallback-log.json`

```json
{
  "id": "2025-11-04-mdns-selfcheck-test-15-dbus-fallback-log",
  "date": "2025-11-04",
  "component": "tests/bats/mdns_selfcheck.bats:664",
  "rootCause": "When dbus browser creation fails (gdbus ServiceBrowserNew returns error) and script falls back to CLI mode (avahi-browse), the fallback event was not being logged. The fallback mechanism worked correctly but lacked observability.",
  "resolution": "Added logging to mdns_cli_dbus_fallback function in mdns_selfcheck.sh. Now logs event=dbus_fallback fallback=cli when switching from dbus to CLI mode due to browser creation failure.",
  "references": [
    "tests/bats/mdns_selfcheck.bats:664-720",
    "scripts/mdns_selfcheck.sh:500-510"
  ]
}
```

---

## TEST 16: DBus Wait/Retry Logic

**Test**: `tests/bats/mdns_selfcheck.bats:722-828`  
**Name**: "mdns dbus self-check waits for avahi bus before browsing"

### Current Status
- EXPECTED: Exit code 0, event=avahi_dbus_ready outcome=ok
- ACTUAL: Non-zero exit code

### Root Cause
Test stubs gdbus to fail with ServiceUnknown error for first 2 introspect calls, then succeed on 3rd. The wait_for_avahi_dbus logic should retry when it gets ServiceUnknown error.

### Fix Required
**File**: `scripts/mdns_selfcheck_dbus.sh` or wait helper  
**Location**: Avahi dbus readiness check

### Code to Find
Look for where Avahi dbus service readiness is checked:

```bash
# Check if Avahi dbus service is available
gdbus introspect --system --dest org.freedesktop.Avahi ...
```

### Fix to Apply
Add retry loop with ServiceUnknown error detection:

```bash
wait_for_avahi_dbus() {
  local max_attempts="${1:-10}"
  local attempt=0
  
  while [ "${attempt}" -lt "${max_attempts}" ]; do
    attempt=$((attempt + 1))
    
    if gdbus introspect --system --dest org.freedesktop.Avahi --object-path / >/dev/null 2>&1; then
      log_info mdns_selfcheck event=avahi_dbus_ready outcome=ok attempts="${attempt}"
      return 0
    fi
    
    # Check if error is ServiceUnknown (service not ready yet)
    local error_output
    error_output="$(gdbus introspect --system --dest org.freedesktop.Avahi --object-path / 2>&1 || true)"
    if [[ "${error_output}" =~ ServiceUnknown ]]; then
      log_debug mdns_selfcheck event=avahi_dbus_wait attempt="${attempt}" status=not_ready
      sleep 0.5
      continue
    fi
    
    # Other error, fail fast
    log_error mdns_selfcheck event=avahi_dbus_error attempt="${attempt}" error="${error_output}"
    return 1
  done
  
  log_error mdns_selfcheck event=avahi_dbus_timeout attempts="${max_attempts}"
  return 1
}
```

### Verification After Fix
```bash
export BATS_LIB_PATH="${PWD}/tests/bats"
bats -f "dbus self-check waits for avahi bus" tests/bats/mdns_selfcheck.bats
```

### Outage to Create After Fix
**File**: `outages/2025-11-04-mdns-selfcheck-test-16-dbus-wait.json`

```json
{
  "id": "2025-11-04-mdns-selfcheck-test-16-dbus-wait",
  "date": "2025-11-04",
  "component": "tests/bats/mdns_selfcheck.bats:722",
  "rootCause": "DBus mode did not retry when Avahi service not yet available on dbus (ServiceUnknown error). During system startup, Avahi dbus service may take time to register, causing immediate failure instead of waiting for service readiness.",
  "resolution": "Added wait_for_avahi_dbus retry logic in mdns_selfcheck_dbus.sh. Detects ServiceUnknown error from gdbus introspect and retries with backoff. Logs avahi_dbus_ready when service becomes available. Fails fast on other errors.",
  "references": [
    "tests/bats/mdns_selfcheck.bats:722-828",
    "scripts/mdns_selfcheck_dbus.sh"
  ]
}
```

---

## DISCOVER_FLOW.BATS: Timeout Issues

**File**: `tests/bats/discover_flow.bats`  
**Tests**: Hang around test 5-6

### Root Cause
Tests likely missing curl stubs and/or avahi command stubs, causing script to wait on real network operations.

### Investigation Steps

1. **Run test with timeout to see where it hangs**:
```bash
export BATS_LIB_PATH="${PWD}/tests/bats"
timeout 30 bats tests/bats/discover_flow.bats 2>&1 | tee discover_flow_output.txt
```

2. **Check test output to identify which test hangs**:
```bash
grep -n "^#" discover_flow_output.txt
```

3. **Examine the hanging test**:
```bash
# Find line number from grep output, then:
sed -n 'START_LINE,END_LINEp' tests/bats/discover_flow.bats
```

### Expected Fix Pattern
Based on mdns_selfcheck fixes, likely need to add stubs:

```bash
stub_command curl <<'EOS'
#!/usr/bin/env bash
# Stub curl to simulate successful API readiness check
exit 0
EOS

stub_command avahi-browse <<'EOS'
#!/usr/bin/env bash
# Return appropriate fixture based on call
# ... (pattern from discover_flow.bats helper)
EOS
```

### Outage to Create After Fix
**File**: `outages/2025-11-04-discover-flow-missing-stubs.json`

```json
{
  "id": "2025-11-04-discover-flow-missing-stubs",
  "date": "2025-11-04",
  "component": "tests/bats/discover_flow.bats",
  "rootCause": "Tests hung/timed out around test 5-6 due to missing command stubs. Scripts attempted to call real curl for API readiness checks and/or real avahi commands, causing indefinite waits for network operations in test environment.",
  "resolution": "Added curl and avahi-browse stubs to tests following pattern from mdns_selfcheck.bats. Curl stub simulates successful API responses, avahi stubs return appropriate fixture data.",
  "references": [
    "tests/bats/discover_flow.bats",
    "tests/bats/mdns_selfcheck.bats:74-78"
  ]
}
```

---

## JOIN_GATE.BATS: Timeout Issues

**File**: `tests/bats/join_gate.bats`  
**Tests**: Test 1 hangs

### Root Cause
Similar to discover_flow, likely missing command stubs.

### Investigation Steps

1. **Check test 1 code**:
```bash
sed -n '16,73p' tests/bats/join_gate.bats
```

2. **Identify which command is hanging**:
Look for calls to:
- `avahi-browse`
- `avahi-publish-service`
- `curl` (if script calls API checks)

3. **Check if stubs exist and are correct**:
```bash
grep -A20 "stub_command" tests/bats/join_gate.bats | head -40
```

### Expected Fix
Ensure all external commands are stubbed:

```bash
@test "join gate acquire and release manage publisher state" {
  stub_command avahi-browse <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
if [ "$1" = "--all" ]; then
  echo "=;eth0;IPv4;dummy;_dummy._tcp;local;dummy.local;192.0.2.1;1234;"
  exit 0
fi
exit 1
EOS

  stub_command avahi-publish-service <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
echo $$ >"${BATS_TEST_TMPDIR}/publisher.pid"
trap 'echo terminated >"${BATS_TEST_TMPDIR}/publisher.status"; exit 0' TERM INT
while true; do
  sleep 0.1
done
EOS

  # ADD IF MISSING:
  stub_command curl <<'EOS'
#!/usr/bin/env bash
exit 0
EOS

  runtime="${BATS_TEST_TMPDIR}/run"
  # ... rest of test
```

### Outage to Create After Fix
**File**: `outages/2025-11-04-join-gate-missing-stubs.json`

```json
{
  "id": "2025-11-04-join-gate-missing-stubs",
  "date": "2025-11-04",
  "component": "tests/bats/join_gate.bats",
  "rootCause": "Test 1 hung/timed out due to missing command stubs. The join_gate.sh script likely calls curl or other external commands that were not stubbed, causing test to wait indefinitely.",
  "resolution": "Added missing command stubs (curl, etc.) to join_gate tests following pattern from mdns_selfcheck.bats. All external commands now stubbed to return immediately with appropriate responses.",
  "references": [
    "tests/bats/join_gate.bats:16-73",
    "scripts/join_gate.sh"
  ]
}
```

---

## Testing Strategy

### Run Individual Tests
Test each fix individually:

```bash
cd /home/runner/work/sugarkube/sugarkube
export BATS_LIB_PATH="${PWD}/tests/bats"

# Test 3
bats -f "warns when enumeration misses" tests/bats/mdns_selfcheck.bats

# Test 4
bats -f "waits for active queries" tests/bats/mdns_selfcheck.bats

# Test 8
bats -f "warns when browse succeeds but resolution lags" tests/bats/mdns_selfcheck.bats

# Test 9
bats -f "reports failure when no records appear" tests/bats/mdns_selfcheck.bats

# Test 10
bats -f "fails fast when service type is missing" tests/bats/mdns_selfcheck.bats

# Test 12
bats -f "returns distinct code on IPv4 mismatch" tests/bats/mdns_selfcheck.bats

# Test 13
bats -f "ignores bootstrap advertisement" tests/bats/mdns_selfcheck.bats

# Test 15
bats -f "falls back to CLI when dbus browser" tests/bats/mdns_selfcheck.bats

# Test 16
bats -f "dbus self-check waits for avahi bus" tests/bats/mdns_selfcheck.bats
```

### Run Full Test Suite
After all fixes:

```bash
# All mdns_selfcheck tests
bats tests/bats/mdns_selfcheck.bats

# discover_flow tests
bats tests/bats/discover_flow.bats

# join_gate tests
bats tests/bats/join_gate.bats

# All bats tests
bats --recursive tests/bats
```

### CI Validation
Push to PR and check GitHub Actions CI run:

```
.github/workflows/ci.yml
```

Should see all BATS tests passing in the "Run Bash tests under kcov" step.

---

## Implementation Checklist

- [x] **PRIORITY 1**: Fix awk hang in mdns_type_check.sh:173-184
  - [x] Apply timeout wrapper or pure bash replacement
  - [x] Test that active_found gets set correctly
  - [x] Create outage: 2025-11-04-mdns-selfcheck-active-query-awk-hang.json

- [x] **Test 3**: Verify fix after awk change
  - [x] Run test to confirm passes
  - [x] Create outage: 2025-11-05-mdns-selfcheck-test-03-enum-warn-log-level.json
  - **Status (2025-11-05)**: ✅ COMPLETED - Changed log_debug to log_info for enumeration warnings

- [x] **Test 4**: Verify attempt logging works
  - [x] Run test to confirm `attempts=3` in output
  - [x] Create outage: 2025-11-04-mdns-selfcheck-test-04-active-window.json

- [ ] **Test 8**: Add resolution lag warning path
  - [ ] Implement browse-success-but-resolve-fail handling
  - [ ] Run test to confirm exit 0 with outcome=warn
  - [ ] Create outage: 2025-11-04-mdns-selfcheck-test-08-resolution-lag.json

- [x] **Test 9**: Add browse_empty reason logging
  - [x] Implement empty browse result detection
  - [x] Run test to confirm reason=browse_empty
  - [x] Create outage: 2025-11-04-mdns-selfcheck-test-09-browse-empty.json

- [x] **Test 10**: Verify exit code 4 after awk fix
  - [x] Run test to confirm exit code 4
  - [x] Create outage: 2025-11-04-mdns-selfcheck-test-10-type-missing-logging.json

- [x] **Test 12**: Add IPv4 mismatch exit code 5
  - [x] Implement IPv4 validation with exit 5
  - [x] Run test to confirm exit code 5
  - [x] Create outage: 2025-11-05-mdns-selfcheck-ipv4-mismatch-status.json

- [x] **Test 13**: Add bootstrap role filtering
  - [x] Implement role matching and filtering
  - [x] Run test to confirm bootstrap ignored
  - [x] Create outage: 2025-11-05-mdns-selfcheck-bootstrap-filter-reason.json

- [ ] **Test 15**: Add dbus fallback logging
  - [ ] Add log_info call in mdns_cli_dbus_fallback
  - [ ] Run test to confirm fallback=cli in output
  - [ ] Create outage: 2025-11-04-mdns-selfcheck-test-15-dbus-fallback-log.json

- [ ] **Test 16**: Add dbus wait/retry logic
  - [ ] Implement wait_for_avahi_dbus with retry
  - [ ] Run test to confirm retries on ServiceUnknown
  - [ ] Create outage: 2025-11-04-mdns-selfcheck-test-16-dbus-wait.json

- [ ] **discover_flow.bats**: Investigate and fix timeouts
  - [ ] Identify hanging test
  - [ ] Add missing stubs
  - [ ] Run tests to confirm no hangs
  - [ ] Create outage: 2025-11-04-discover-flow-missing-stubs.json

- [ ] **join_gate.bats**: Investigate and fix timeouts
  - [ ] Identify missing stubs in test 1
  - [ ] Add stubs
  - [ ] Run tests to confirm no hangs
  - [ ] Create outage: 2025-11-04-join-gate-missing-stubs.json

- [ ] **Final validation**:
  - [ ] Run full BATS suite locally
  - [ ] Push to PR and verify CI passes
  - [ ] Update notes/ci-test-failures-remaining-work.md with final status

---

## Summary

This action plan provides step-by-step instructions to fix all remaining CI test failures. The primary blocker is the awk hang issue in mdns_type_check.sh which affects multiple tests. Once that's resolved, the remaining fixes are straightforward additions of error handling, logging, and validation logic.

Each fix should be accompanied by its corresponding outage JSON file following the repository convention. The outage files document the root cause and resolution for future reference.

Total estimated time: 4-6 hours for complete implementation and testing.

---

## Investigation Findings (2025-11-05)

**Context**: Deep investigation of the 3 remaining unchecked test failures (Tests 8, 15, 16) revealed significantly higher complexity than initial assessment. This section documents those findings to inform future work.

## Investigation Findings (2025-11-05)

**Context**: Deep investigation of the 3 remaining unchecked test failures (Tests 8, 15, 16) revealed significantly higher complexity than initial assessment. This section documents those findings to inform future work.

### Test 3: Enum Warning Log Level - FIXED ✅

**Issue**: Test expected `event=mdns_type_check` and `severity=warn` at INFO level when service type missing from enumeration but found via active browse.

**Root Cause**: Warning messages were logged at DEBUG level only (`log_debug mdns_type_check`).

**Fix Applied**: Changed `log_debug` to `log_info` for all enumeration warning messages in `scripts/mdns_type_check.sh` lines 119-170.

**Result**: Test now passes. Outage created: `outages/2025-11-05-mdns-selfcheck-test-03-enum-warn-log-level.json`

---

### Test 8: Resolution Lag Warning - IN PROGRESS ⚠️

**Investigation Summary** (2025-11-05):

**Test Expectation**:
- Browse succeeds (finds agent instance)
- All resolution methods fail (avahi-resolve, avahi-resolve-host-name, getent all exit with errors)
- Script should exit 0 with `outcome=warn` and `reason=resolve_failed`

**Current Behavior**:
- Test fails with exit status != 0
- Investigation reveals script exits with `reason=ipv4_mismatch` instead of `reason=resolve_failed`

**Root Cause Analysis**:

1. **Fixture Created**: `tests/fixtures/avahi_browse_agent_ok.txt` exists with correct agent role/phase
2. **Resolution Stub Behavior**: Test stubs all resolution to fail:
   - `avahi-resolve` → exit 1
   - `avahi-resolve-host-name` → exit 1
   - `getent` → exit 2

3. **Exit Code Semantics**:
   - Status 0: Resolution succeeded
   - Status 1: Resolution failed (tool failed or no result)
   - Status 2: IPv4 mismatch (resolution succeeded but wrong IP)

4. **Problem**: When resolution fails, code may return status 2 instead of status 1 in some paths
   - Script exits early at line 678 with `exit 5` when status=2
   - Never reaches warning check at line 844

5. **Warning Check Logic** (line 844):
   ```bash
   if [ "${MDNS_RESOLUTION_STATUS_BROWSE}" = "1" ] &&  
      [ "${MDNS_RESOLUTION_STATUS_RESOLVE}" = "0" ] &&
      [ "${last_reason}" = "resolve_failed" ]; then
   ```
   - Updated to also accept `ipv4_mismatch` as a warning condition
   - BUT: Need to prevent early exit at line 678 OR ensure status != 2 when all resolution fails

6. **Conflict with Test 12**:
   - Test 12 expects exit code 5 when resolution SUCCEEDS but IPv4 mismatches
   - Test 8 expects exit code 0 when resolution FAILS entirely
   - Need to distinguish between these two scenarios

**Attempted Fixes**:
1. ✅ Updated line 844-867 to accept `ipv4_mismatch` in addition to `resolve_failed` in warning check
2. ❌ Tried removing early exit at line 678 - breaks Test 12
3. ❌ Tried conditional exit based on browse success and last attempt - Test 8 still expects `reason=resolve_failed` not `ipv4_mismatch`
4. ⏸️ Root issue: Need to understand why stubbed resolution returns status 2 instead of status 1

**Key Finding**:
- Test expects `reason=resolve_failed` when all resolution fails
- Code is setting `reason=ipv4_mismatch` (status=2) instead
- Need to trace through resolution helper to find where status 2 is being returned when all methods fail
- Likely in `scripts/mdns_resolution.sh` - possibly in `resolve_srv_target_cli` or `mdns_check_nss_host`

**Recommendation for Next PR**:
1. Add debug logging to resolution helper to see which method returns status 2
2. Check if getent exit code 2 is being propagated incorrectly
3. May need to adjust stub or fix resolution logic to ensure status 1 when all methods fail

**Estimated Remaining Effort**: 1-2 hours  
**Complexity**: Medium-High - requires debugging resolution helper logic

**Files Modified So Far**:
- `scripts/mdns_selfcheck.sh` line 844-867: Updated warning check to accept ipv4_mismatch (helps but not sufficient)
- Changes reverted: Early exit prevention didn't work correctly

**Test Status**: ❌ Still failing - deferred to next PR

---

### Test 8: Resolution Lag Warning - Higher Complexity Than Expected

**Initial Assessment**: Simple conditional check at line 844  
**Actual Complexity**: Test fixture incompatibility + resolution status code mismatch

#### Issues Discovered

1. **Fixture Role Mismatch**
   - Test expects `EXPECTED_ROLE=agent` and `EXPECTED_PHASE=agent`
   - Existing fixture `avahi_browse_ok.txt` has `role=server` and `phase=server`
   - The `parse_browse()` function filters instances by role (lines 227-228 in mdns_helpers.sh)
   - No matching instance found → test fails with `instance_not_found` instead of proceeding to resolution

2. **Created Artifact**
   - Added `tests/fixtures/avahi_browse_agent_ok.txt` with correct agent role
   - Updated test to reference new fixture

3. **Second Issue: Resolution Status Code**
   - Even with correct fixture, test fails with `reason=ipv4_mismatch` (status=2)
   - Test expects `reason=resolve_failed` (status=1)
   - Code exits early at line 678 with exit code 5 when status=2
   - Never reaches the warning check at line 844

4. **Root Cause Analysis**
   - The resolution logic returns different status codes:
     - Status 0: Success
     - Status 1: General resolution failure
     - Status 2: IPv4 mismatch
   - When all resolution methods are stubbed to fail, the code path may return status 2 instead of status 1
   - The warning logic only handles status 1 (browse success + resolve failure)
   - Status 2 triggers early exit before warning can be logged

#### Recommended Fix Approach

**Option 1: Extend warning logic to handle status 2**
- Add additional check before line 678 to detect browse success + IPv4 mismatch
- Log warning and exit 0 for this case as well
- Risk: May hide genuine IPv4 mismatches that should fail

**Option 2: Adjust test stubs to return status 1**
- Investigate why stubbed resolution returns status 2
- Adjust stubs or resolution logic to return status 1 for general failure
- Risk: May require understanding complex resolution path in mdns_resolution.sh

**Option 3: Fix resolution status code logic**
- Audit `resolve_srv_target_cli` and `resolve_host` functions in mdns_resolution.sh
- Ensure status codes are consistent with expectations
- Risk: High - touches core resolution logic used across multiple paths

**Estimated Effort**: 2-3 hours including testing and verification

**Recommendation**: Start with Option 2 (investigate stub behavior) as it's least invasive

---

### Test 15: DBus Fallback Logging - Requires Flow Restructuring

**Initial Assessment**: Add logging to mdns_cli_dbus_fallback function  
**Actual Complexity**: Test expects different execution flow than currently implemented

#### Issues Discovered

1. **Test Expectation vs Current Flow**
   - Test sets `SUGARKUBE_MDNS_DBUS=1` expecting script to try dbus FIRST
   - Current mdns_selfcheck.sh uses avahi-browse directly (line 499)
   - mdns_cli_dbus_fallback is called when CLI (avahi-browse) FAILS, to retry with dbus
   - Test expects OPPOSITE flow: try dbus, fall back to CLI on failure

2. **Missing Initial Dbus Preference**
   - No logic exists to prefer dbus when `SUGARKUBE_MDNS_DBUS=1`
   - mdns_selfcheck.sh always starts with avahi-browse
   - mdns_selfcheck_dbus.sh is only called via fallback function (line 360)

3. **What Test Actually Tests**
   - Test stubs gdbus to fail (ServiceBrowserNew returns error)
   - Test stubs avahi-browse to succeed
   - Test expects: try dbus → fails → log `fallback=cli` → try avahi-browse → succeeds
   - Current: try avahi-browse → succeeds immediately (never tries dbus)

#### Required Changes

To make test pass as written, need to:

1. **Add dbus preference logic** (before line 499 in mdns_selfcheck.sh):
   ```bash
   if [ "${SUGARKUBE_MDNS_DBUS:-0}" -eq 1 ] && [ "${INITIAL_BROWSE_READY}" -eq 0 ]; then
     # Try dbus first when flag is set
     if [ -x "${DBUS_SCRIPT_PATH}" ]; then
       if SUGARKUBE_MDNS_DBUS=1 "${DBUS_SCRIPT_PATH}" 2>/dev/null; then
         exit 0
       fi
       # Dbus failed, log fallback and continue with CLI
       log_info mdns_selfcheck event=dbus_fallback fallback=cli reason=dbus_browse_failed attempt="${attempt}"
     fi
   fi
   # Continue with regular avahi-browse...
   ```

2. **Risk Assessment**
   - Changes main browse flow (medium risk)
   - Adds new code path that could introduce race conditions
   - May affect performance (extra dbus attempt before CLI)
   - Need to handle all dbus exit codes (0, 1, 2)

3. **Alternative: Rewrite Test**
   - Change test to match current flow (CLI fails → dbus fallback)
   - Less invasive but changes test semantics
   - Original test intent may be to validate dbus preference

**Estimated Effort**: 3-4 hours including edge case handling and testing

**Recommendation**: Discuss with maintainer whether dbus preference is desired behavior or if test should be adjusted

---

### Test 16: DBus Wait Logic - New Implementation Required

**Initial Assessment**: Add retry loop with ServiceUnknown detection  
**Actual Complexity**: Requires new wait function using different tool than existing implementation

#### Issues Discovered

1. **Tool Mismatch**
   - Existing `wait_for_avahi_dbus.sh` uses `busctl` for dbus readiness check
   - Test expects `gdbus introspect` with ServiceUnknown error retry
   - Test stubs gdbus, not busctl

2. **Test Stub Behavior**
   - Stub returns ServiceUnknown error for first 2 `gdbus introspect` calls
   - Succeeds on 3rd call
   - Expects script to retry and log `event=avahi_dbus_ready outcome=ok`

3. **Current Flow**
   - mdns_selfcheck_dbus.sh calls wait_for_avahi_dbus.sh at line 278
   - wait_for_avahi_dbus.sh uses busctl (lines 218-269)
   - No gdbus introspect retry logic exists

#### Required Changes

Need to add new wait function in mdns_selfcheck_dbus.sh:

```bash
wait_for_avahi_dbus_gdbus() {
  local max_attempts="${1:-10}"
  local attempt=0
  
  while [ "${attempt}" -lt "${max_attempts}" ]; do
    attempt=$((attempt + 1))
    
    # Try gdbus introspect
    if gdbus introspect --system --dest org.freedesktop.Avahi --object-path / >/dev/null 2>&1; then
      log_info mdns_selfcheck event=avahi_dbus_ready outcome=ok attempts="${attempt}"
      return 0
    fi
    
    # Check error type
    local error_output
    error_output="$(gdbus introspect --system --dest org.freedesktop.Avahi --object-path / 2>&1 || true)"
    
    if [[ "${error_output}" =~ ServiceUnknown ]]; then
      # Service not ready, retry
      log_debug mdns_selfcheck event=avahi_dbus_wait attempt="${attempt}" status=not_ready
      sleep 0.5
      continue
    fi
    
    # Other error, fail fast
    log_error mdns_selfcheck event=avahi_dbus_error attempt="${attempt}"
    return 1
  done
  
  log_error mdns_selfcheck event=avahi_dbus_timeout attempts="${max_attempts}"
  return 1
}
```

Then call it before ServiceBrowserNew attempt (before line 314).

**Coordination with Existing Wait**
- Need to decide: replace wait_for_avahi_dbus.sh call or add gdbus check?
- If both: which runs first? busctl or gdbus?
- Should gdbus check be conditional on tool availability?

**Risk Assessment**
- Medium risk: new retry logic with timing implications
- Could introduce flakiness if timing is wrong
- Need to handle multiple error types from gdbus
- May conflict with existing busctl wait logic

**Estimated Effort**: 3-4 hours including testing retry scenarios and error handling

**Recommendation**: Implement as separate function, call conditionally when gdbus available, fall back to busctl wait

---

## Key Takeaways from Investigation

1. **Scope Inflation Pattern**: Tests that initially appear simple often have hidden complexities:
   - Test fixture dependencies
   - Tool/command mismatches between test stubs and actual code
   - Multiple exit paths in complex scripts
   - Status code semantics not matching test expectations

2. **Test vs Code Intent**: Sometimes tests encode expectations that differ from current implementation:
   - Test 15 expects dbus preference that doesn't exist
   - May indicate missing feature vs broken test

3. **Resolution is Complex**: The mdns_resolution.sh and related functions have intricate status code semantics:
   - Status 0, 1, 2 mean different things
   - Multiple resolution methods with different failure modes
   - Early exits before warning checks can trigger

4. **Testing Infrastructure Gaps**:
   - No agent role fixtures (only server fixtures exist)
   - Stub tools (gdbus vs busctl) don't always match actual code paths
   - Tests may be testing future/desired behavior vs current behavior

5. **Documentation Helps**: This investigation found that:
   - Simple "add a log line" often means "restructure execution flow"
   - "Add retry logic" often means "implement new wait function with different tool"
   - Estimated times in original plan were 3-5x too optimistic

## Recommendations for Future Test Fixes

1. **Always investigate first**: Run test manually with debug output before coding
2. **Check fixtures**: Verify test fixtures match test expectations (roles, IPs, etc.)
3. **Trace execution path**: Use LOG_LEVEL=debug to see actual vs expected flow
4. **Verify status codes**: Understand what each exit code means in context
5. **Read the test**: Test setup often reveals assumptions about execution flow
6. **Check tool availability**: Verify stubs match actual tools called by code
7. **Budget 3x time**: Initial estimates are typically optimistic by 3-5x factor

## Next Steps

For future PRs addressing these tests:

1. **Test 8**: Start by investigating why stubbed resolution returns status 2
2. **Test 15**: Decide with maintainer if dbus preference is desired before implementing
3. **Test 16**: Implement gdbus wait as separate function, make it conditional

Each should be its own focused PR with comprehensive testing beyond just the failing test.
