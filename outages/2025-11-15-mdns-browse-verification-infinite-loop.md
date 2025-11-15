# mDNS Browse Verification Infinite Loop

**Date**: 2025-11-15  
**Component**: `scripts/k3s-discover.sh` - browse verification in service publishing  
**Severity**: Critical (bootstrap hangs indefinitely, k3s never starts)  
**Status**: Resolved

## Problem Statement

Bootstrap nodes hang indefinitely during service verification when `SAVE_DEBUG_LOGS=1`, preventing k3s from starting. The script becomes unresponsive after successfully publishing the mDNS service and passing self-checks.

## Observed Behavior

From `logs/up/20251115T070652Z_d3ad6d5_sugarkube0_just-up-dev.log`:

```
ts=2025-11-14T23:17:04-08:00 level=info event=mdns_selfcheck outcome=confirmed 
  role=server host=sugarkube0.local observed=sugarkube0.local phase=server check=initial
[k3s-discover mdns] query_mdns: mode=server-select, cluster=sugar, env=dev
[k3s-discover mdns] query_mdns: service_types=['_k3s-sugar-dev._tcp', '_https._tcp']
[k3s-discover mdns] query_mdns: timeout=30.0s
[k3s-discover mdns] query_mdns: no_terminate=1
[k3s-discover mdns] _load_lines_from_avahi: browsing service_type=_k3s-sugar-dev._tcp, resolve=True
[k3s-discover mdns] _invoke_avahi: command=avahi-browse --parsable --resolve --ignore-local _k3s-sugar-dev._tcp
[k3s-discover mdns] _invoke_avahi: timeout=30.0s
<script hangs here indefinitely>
```

The bootstrap node:
- Successfully bootstrapped k3s
- Published mDNS service
- Passed self-checks confirming service is visible
- Started browse verification for debug logging
- **Hung indefinitely** at avahi-browse invocation

## Root Cause

### Environment Variable Persistence

The `discover_via_nss_and_api()` function (line 4616) exports `SUGARKUBE_MDNS_NO_TERMINATE=1`:

```bash
# For simple discovery, we want avahi-browse to wait for network responses
# instead of just checking the cache.
export SUGARKUBE_MDNS_NO_TERMINATE=1
```

This is correct for initial discovery - it allows avahi-browse to actively listen for mDNS announcements from the network instead of only checking cached entries.

**However**, this environment variable persists throughout the entire script execution.

### Browse Verification Inherits the Setting

When `SAVE_DEBUG_LOGS=1`, both `publish_api_service()` (line 3408) and `publish_bootstrap_service()` (line 3456) perform browse verification:

```bash
if [ "${SAVE_DEBUG_LOGS:-0}" = "1" ]; then
  local browse_verification
  browse_verification="$(SUGARKUBE_DEBUG=1 run_avahi_query server-select | head -n1 || true)"
  # ... rest of verification
fi
```

Because `SUGARKUBE_MDNS_NO_TERMINATE=1` is still set, the verification call:
1. Calls `run_avahi_query server-select`
2. Which calls `k3s_mdns_query.py::query_mdns()`
3. Which calls `_build_command()` with `NO_TERMINATE=1`
4. Which **omits** the `--terminate` flag from avahi-browse
5. avahi-browse waits indefinitely for network responses

### Why This Causes an Infinite Loop

From `k3s_mdns_query.py` (lines 54-60):

```python
# --terminate causes avahi-browse to dump only cached entries and exit immediately.
# For initial cluster formation, we want to wait for network responses,
# so we skip --terminate when SUGARKUBE_MDNS_NO_TERMINATE=1.
use_terminate = os.environ.get(_NO_TERMINATE_ENV, "0").strip() != "1"
if use_terminate:
    command.append("--terminate")
```

Without `--terminate`, avahi-browse:
- Actively listens for mDNS announcements
- Waits for multicast responses
- Never exits on its own (no termination condition)
- Relies on subprocess timeout to kill it

However, the browse verification happens **after** the service is already published and confirmed. At this point:
- The service is in the local Avahi cache
- We only want to verify it's browsable (quick check)
- We don't need to wait for network responses
- We want `--terminate` for a fast cache-only lookup

## Timeline

1. **Initial Discovery** (correct behavior)
   - `discover_via_nss_and_api()` exports `NO_TERMINATE=1`
   - Bootstrap node tries to find existing servers
   - No servers found (expected - first node)
   - Proceeds to bootstrap

2. **Bootstrap Process** (correct behavior)
   - Installs k3s with `cluster-init`
   - Waits for API to become ready
   - API responds with 401 (correct - unauthorized but alive)

3. **Service Publication** (correct behavior)
   - Publishes mDNS service via `publish_api_service()`
   - Self-check confirms service is visible locally
   - Service advertised successfully

4. **Browse Verification** (BUG - infinite loop)
   - `SAVE_DEBUG_LOGS=1` triggers browse verification
   - Calls `run_avahi_query server-select`
   - Inherits `NO_TERMINATE=1` from environment
   - avahi-browse waits indefinitely
   - Script hangs forever

## Impact

- Bootstrap nodes never complete startup
- k3s never starts serving requests
- Cluster formation is impossible
- Only affects debug mode (`SAVE_DEBUG_LOGS=1`)
- Critical for development and troubleshooting

## Resolution

### The Fix

Modified both browse verification calls to explicitly override `SUGARKUBE_MDNS_NO_TERMINATE=0`:

**In `publish_api_service()` (line 3410):**
```bash
browse_verification="$(SUGARKUBE_MDNS_NO_TERMINATE=0 SUGARKUBE_DEBUG=1 run_avahi_query server-select | head -n1 || true)"
```

**In `publish_bootstrap_service()` (line 3460):**
```bash
browse_verification="$(SUGARKUBE_MDNS_NO_TERMINATE=0 SUGARKUBE_DEBUG=1 run_avahi_query server-select | head -n1 || true)"
```

### Why This Works

Setting `SUGARKUBE_MDNS_NO_TERMINATE=0` in the command substitution:
1. Creates a subshell with the override
2. The override only affects that specific call
3. avahi-browse gets the `--terminate` flag
4. Returns cached results immediately (no network wait)
5. Browse verification completes in milliseconds
6. Script continues normally

### What's Preserved

- Initial discovery still uses `NO_TERMINATE=1` (correct)
- Network-based service discovery works as intended
- Only the verification step is affected
- Debug logging still captures verification results

## Prevention

### Test Coverage

Added comprehensive tests in `tests/scripts/test_browse_verification_no_terminate_fix.py`:

1. **test_publish_api_service_browse_verification_overrides_no_terminate**
   - Verifies `publish_api_service()` sets `NO_TERMINATE=0` for browse verification
   - Prevents regression to infinite loop behavior

2. **test_publish_bootstrap_service_browse_verification_overrides_no_terminate**
   - Verifies `publish_bootstrap_service()` sets `NO_TERMINATE=0` for browse verification
   - Mirrors the api_service test for bootstrap path

3. **test_discover_via_nss_and_api_sets_no_terminate**
   - Verifies initial discovery still uses `NO_TERMINATE=1`
   - Ensures the intended behavior is preserved

### Validation

- All tests pass
- Bash syntax validated
- Shellcheck reports no new issues
- Changes are surgical and localized

## Lessons Learned

1. **Environment Variable Scope**: Exported variables persist throughout script execution and can cause unexpected behavior in later function calls.

2. **Context-Dependent Behavior**: The same tool (avahi-browse) needs different flags depending on context:
   - Initial discovery: wait for network responses
   - Verification: check cached results only

3. **Debug Mode Risks**: Debug logging paths should be as fast and reliable as production paths. Long-running debug operations can mask or introduce new issues.

4. **Timeout Limitations**: While subprocess timeouts exist, waiting 30 seconds for a verification step that should take milliseconds is poor UX and may be confused for system slowness.

## Related Issues

- **2025-11-15-avahi-browse-terminate-cache-only.json**: Original issue that introduced `NO_TERMINATE` flag
- **2025-11-15-phase3-phase4-incompatibility.json**: Phase 3 discovery changes
- **2025-11-15-discovery-visibility-gap.md**: Real-world testing that revealed network discovery issues

## References

- **Code Changes**:
  - `scripts/k3s-discover.sh` lines 3408, 3456 (browse verification calls)
  - `scripts/k3s-discover.sh` line 4616 (discover_via_nss_and_api NO_TERMINATE export)
  
- **Tests**:
  - `tests/scripts/test_browse_verification_no_terminate_fix.py`
  
- **Logs**:
  - `logs/up/20251115T070652Z_d3ad6d5_sugarkube0_just-up-dev.log`

- **Related Documentation**:
  - `scripts/k3s_mdns_query.py` (NO_TERMINATE implementation)
  - `docs/raspi_cluster_setup.md` (user-facing setup guide)
