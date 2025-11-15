# avahi-browse --terminate Cache-Only Bug

**Date**: 2025-11-15  
**Component**: `scripts/k3s_mdns_query.py` - avahi-browse command builder  
**Severity**: Critical (cluster formation impossible)  
**Status**: Resolved

## Problem Statement

Testing Raspberry Pi 5 cluster setup revealed that joining nodes (sugarkube1) could not discover bootstrap nodes (sugarkube0), preventing cluster formation, even though service advertisement was properly enabled and working.

## Observed Behavior

### sugarkube0 (bootstrap node)
```
ts=2025-11-14T17:49:04-08:00 level=info event=mdns_publish outcome=ok role=server 
  confirm_outcome=ok confirm_latency_ms=1101 confirm_attempts=1 
  confirm_dbus_status=1 confirm_cli_status=0 reload_status=0
```

The bootstrap node successfully:
- Published its mDNS service
- Confirmed via `avahi-browse` that the service is advertised (`confirm_cli_status=0`)

### sugarkube1 (joining node)
```
ts=2025-11-14T17:50:44-08:00 level=info event=discover event=simple_discovery_start 
  phase=discover_via_service_browse
ts=2025-11-14T17:50:46-08:00 level=info event=discover event=simple_discovery_no_servers 
  token_present=1
ts=2025-11-14T17:50:46-08:00 level=info event=discover msg="Simple discovery failed and 
  token is present; cannot bootstrap" severity=error
```

The joining node:
- Started discovery at 17:50:44 (1 minute 42 seconds after sugarkube0 published)
- Completed discovery at 17:50:46 (**only 2 seconds of browsing**)
- Found no services
- Failed to join

## Root Cause

The `--terminate` flag in `avahi-browse` causes it to:
1. Query the local Avahi daemon's cached service entries
2. Dump what it finds
3. Exit immediately

**Critically**: It does NOT wait for or listen to multicast mDNS announcements from the network!

### Why Services Weren't Cached

When sugarkube1 started, its Avahi daemon had not yet received or cached the service announcements from sugarkube0 because:
- Avahi caches are local to each node
- Multicast mDNS announcements are periodic (not instantaneous)
- The joining node's Avahi daemon may not have been listening when sugarkube0 first announced
- Cache entries have TTLs and may not persist across Avahi restarts

### The Bug in Context

From `k3s_mdns_query.py` (lines 47-52):
```python
def _build_command(mode: str, service_type: str, *, resolve: bool = True) -> List[str]:
    command = [
        "avahi-browse",
        "--parsable",
        "--terminate",  # <-- THE PROBLEM
    ]
```

The retry logic in `_invoke_avahi()` (lines 221-223) breaks immediately when `returncode == 0`:
```python
# If successful or has output, break
if result.returncode == 0 or result.stdout:
    break
```

When `--terminate` is used:
- Exit code is 0 (success)
- Output is empty (no cached services)
- Retry logic treats this as "success" and doesn't retry
- Total time: ~2 seconds (fast cache check)

## Impact

- **Cluster formation impossible**: Joining nodes cannot discover bootstrap nodes
- **False negative**: Service IS advertised but not discovered
- **Misleading logs**: "No servers found" even though server exists and is advertising
- **Timing dependent**: Works if joining node's Avahi cache happens to have the entry
- **Not a network issue**: Multicast works, but `--terminate` doesn't use it

## Resolution

### Code Changes

**1. Added environment variable support** (`k3s_mdns_query.py` lines 18, 47-59):

```python
_NO_TERMINATE_ENV = "SUGARKUBE_MDNS_NO_TERMINATE"

def _build_command(mode: str, service_type: str, *, resolve: bool = True) -> List[str]:
    command = [
        "avahi-browse",
        "--parsable",
    ]
    
    # --terminate causes avahi-browse to dump only cached entries and exit immediately.
    # This is fast but won't discover services that haven't been cached yet.
    # For initial cluster formation, we want to wait for network responses,
    # so we skip --terminate when SUGARKUBE_MDNS_NO_TERMINATE=1.
    use_terminate = os.environ.get(_NO_TERMINATE_ENV, "0").strip() != "1"
    if use_terminate:
        command.append("--terminate")
    
    # ... rest of command building
```

**2. Set environment in simple discovery** (`k3s-discover.sh` lines 4582+):

```bash
discover_via_nss_and_api() {
  # For simple discovery, we want avahi-browse to wait for network responses
  # instead of just checking the cache. This is critical for initial cluster
  # formation when services may not be cached yet.
  export SUGARKUBE_MDNS_NO_TERMINATE=1
  
  # Increase timeout for initial discovery to allow time for service propagation
  # across the network (default is 10s, we use 30s for simple discovery)
  if [ -z "${SUGARKUBE_MDNS_QUERY_TIMEOUT:-}" ]; then
    export SUGARKUBE_MDNS_QUERY_TIMEOUT=30
  fi
  
  # Use existing service browsing infrastructure...
  if select_server_candidate; then
    # ...
  fi
}
```

### How the Fix Works

**Without --terminate**:
1. `avahi-browse` starts and connects to Avahi daemon
2. Registers interest in `_k3s-sugar-dev._tcp` service type
3. **Actively listens to multicast mDNS announcements** on UDP port 5353
4. Waits up to timeout (30 seconds) for services to appear
5. Parses and returns discovered services

**With 30-second timeout**:
- Plenty of time for multicast packets to propagate
- Accommodates network delays, retries, and Avahi daemon processing
- Still faster than previous approaches (leader election took 60+ seconds)

## Verification

After the fix:
1. Bootstrap node publishes service: `_k3s-sugar-dev._tcp` on port 6443 ✅
2. Joining node runs `avahi-browse` **without --terminate** ✅
3. `avahi-browse` listens to multicast announcements ✅
4. Service discovered from network within 30 seconds ✅
5. Joining node validates API (confirms 401 response) ✅
6. Joining node joins cluster successfully ✅

## Lessons Learned

1. **Understand tool behavior**: `--terminate` is documented but its cache-only behavior wasn't obvious
2. **Test cross-node discovery**: Single-node tests don't reveal timing issues
3. **Log timing**: The 2-second completion time was the key diagnostic clue
4. **Read man pages carefully**: `avahi-browse --help` explains --terminate behavior
5. **Question assumptions**: "Service browsing works" needed to be: "Service browsing works **from the network**"

## Related Issues

This bug was masked by earlier issues:
- `2025-11-15-phase3-phase4-incompatibility.json` - Initially thought services weren't being advertised
- `2025-11-14-mdns-discovery-cascade-failure.json` - Avahi restart issues caused failures too
- `2025-11-14-api-readiness-401-rejection.json` - 401 handling prevented earlier discovery testing

Once those were fixed, this --terminate bug became the final blocker for cluster formation.

## Future Considerations

### Performance vs Correctness Trade-off

- **With --terminate**: Fast (2s) but unreliable for initial discovery
- **Without --terminate**: Slower (up to 30s) but reliable

Possible future optimization:
1. Try with --terminate first (fast path for cached entries)
2. If empty result, retry without --terminate (network discovery)
3. Avoids 30s timeout when services are already cached

### Alternative Approaches Considered

**Option A**: Use multicast DNS query tool (dig, mDNStool)
- ❌ Adds new dependencies
- ❌ More complex than fixing avahi-browse usage

**Option B**: Hardcode hostname patterns
- ❌ Breaks dynamic discovery
- ❌ Doesn't work with custom hostnames
- ❌ Violates Phase 3 design principle

**Option C**: Increase retry count instead of removing --terminate
- ❌ Still cache-only, just more retries
- ❌ Doesn't wait for multicast announcements

**Option D**: Current fix (conditional --terminate)
- ✅ Simple one-line environment variable
- ✅ Backward compatible (defaults to old behavior)
- ✅ Enables network-based discovery when needed
- ✅ No new dependencies

## References

- Issue: Raspberry Pi 5 cluster setup logs showing discovery failure
- Fix commit: Add SUGARKUBE_MDNS_NO_TERMINATE support
- Related: `outages/2025-11-15-phase3-phase4-incompatibility.md`
- Roadmap: `notes/2025-11-14-mdns-discovery-fixes-and-simplification-roadmap.md`
