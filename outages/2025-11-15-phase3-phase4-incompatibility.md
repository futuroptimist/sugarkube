# Phase 3/Phase 4 Incompatibility: Discovery Failure

**Date**: 2025-11-15  
**Component**: `scripts/k3s-discover.sh` mDNS discovery system  
**Severity**: Critical (cluster formation impossible)  
**Status**: Resolved

## Problem Statement

Testing Raspberry Pi 5 cluster setup revealed that joining nodes (sugarkube1) could not discover bootstrap nodes (sugarkube0), preventing cluster formation.

## Observed Behavior

### sugarkube0 (bootstrap node)
```
event=simple_discovery_bootstrap reason=no_token
event=service_advertisement_skipped reason=SUGARKUBE_SKIP_SERVICE_ADVERTISEMENT=1 role=bootstrap
```

The bootstrap node successfully started k3s but **skipped publishing its mDNS service advertisement**.

### sugarkube1 (joining node)
```
event=simple_discovery_start phase=discover_via_service_browse
event=simple_discovery_no_servers token_present=1
event=simple_discovery_fail
```

The joining node attempted to discover servers via mDNS service browsing but **found no services** because none were being advertised.

## Root Cause

The mDNS discovery simplification roadmap (documented in `notes/2025-11-14-mdns-discovery-fixes-and-simplification-roadmap.md`) proposed four phases of simplification:

- **Phase 2**: Skip Avahi restart (default: skip, `SUGARKUBE_SKIP_ABSENCE_GATE=1`)
- **Phase 3**: Simplified discovery using service browsing (default: enabled, `SUGARKUBE_SIMPLE_DISCOVERY=1`)
- **Phase 4**: Skip service advertisement (default: skip, `SUGARKUBE_SKIP_SERVICE_ADVERTISEMENT=1`)

The issue: **Phase 3 and Phase 4 defaults were incompatible with each other**.

### Phase 3 Behavior (Simplified Discovery)
When `SUGARKUBE_SIMPLE_DISCOVERY=1` (default):
```bash
discover_via_nss_and_api() {
  # Use service browsing to find servers
  if select_server_candidate; then
    # This calls run_avahi_query which uses avahi-browse
    # to scan for _k3s-{cluster}-{environment}._tcp services
    server_host="${MDNS_SELECTED_HOST}"
    return 0
  fi
  # ...
}
```

Phase 3 **requires** mDNS services to be advertised for `avahi-browse` to discover them.

### Phase 4 Behavior (Skip Service Advertisement)
When `SUGARKUBE_SKIP_SERVICE_ADVERTISEMENT=1` (default):
```bash
publish_api_service() {
  if [ "${SKIP_SERVICE_ADVERTISEMENT}" = "1" ]; then
    log_info mdns_publish event=service_advertisement_skipped \
      reason="SUGARKUBE_SKIP_SERVICE_ADVERTISEMENT=1" role=server
    return 0  # Early exit - no service published!
  fi
  # ... rest of function never executes
}
```

Phase 4 **prevents** mDNS services from being advertised, making them invisible to `avahi-browse`.

### The Incompatibility
```
Phase 3 needs: avahi-browse → find _k3s-sugar-dev._tcp services
Phase 4 does:  skip publishing → no _k3s-sugar-dev._tcp services exist
Result:        avahi-browse finds nothing → discovery fails
```

## Impact

- **Cluster formation impossible**: Joining nodes cannot discover bootstrap nodes
- **Affects all environments**: dev, int, prod all impacted
- **User confusion**: Logs show discovery running but finding nothing
- **No workaround without manual intervention**: Users must manually set environment variables

## Resolution

Changed the default for `SUGARKUBE_SKIP_SERVICE_ADVERTISEMENT` from `1` to `0`.

### Code Changes

**scripts/k3s-discover.sh** (line 200-203):
```bash
# Before:
# Default: 1 (service advertisement skipped; set to 0 for legacy advertisement)
SKIP_SERVICE_ADVERTISEMENT="${SUGARKUBE_SKIP_SERVICE_ADVERTISEMENT:-1}"

# After:
# Default: 0 (service advertisement enabled; set to 1 to skip advertisement)
SKIP_SERVICE_ADVERTISEMENT="${SUGARKUBE_SKIP_SERVICE_ADVERTISEMENT:-0}"
```

**docs/raspi_cluster_setup.md** (Configuration Knobs table):
```markdown
Before: | `SUGARKUBE_SKIP_SERVICE_ADVERTISEMENT` | `1` | Skip mDNS service publishing |
After:  | `SUGARKUBE_SKIP_SERVICE_ADVERTISEMENT` | `0` | When set to `1`, skip mDNS service publishing |
```

**docs/raspi_cluster_setup.md** (Phase 4 section):
- Updated title: "Phase 4: Service Advertisement (Default: Enabled)"
- Clarified that nodes advertise by default
- Documented incompatibility when disabled with Phase 3 enabled
- Removed misleading claim that Phase 4 works with Phase 3

**tests/scripts/test_skip_service_advertisement.py**:
- Updated assertion: default should be `0` not `1`
- Updated test name documentation

## Verification

After the fix:
1. Bootstrap node publishes service: `_k3s-sugar-dev._tcp` on port 6443
2. Joining node discovers via `avahi-browse`: finds service
3. Joining node validates API: confirms 401 response (alive)
4. Joining node joins cluster: uses discovered hostname

## Lessons Learned

1. **Test phase combinations**: When implementing feature flags for multi-phase rollouts, test all combinations of enabled/disabled states
2. **Document dependencies**: Clearly document when one phase depends on another
3. **Validate defaults together**: Default values for related features must be tested together, not in isolation
4. **Regression tests**: Add integration tests that verify phase combinations work end-to-end

## Future Considerations

### If Phase 4 is re-enabled in the future:
Phase 4 (skipping service advertisement) cannot work with Phase 3 (service browsing for discovery). The roadmap document itself acknowledges this:

> **Phase 4 Implementation Steps**: "Phase 3 must be complete first (using NSS resolution)"

The roadmap envisioned Phase 3 as using **NSS resolution** (getent hosts), not service browsing. However, the actual Phase 3 implementation uses `select_server_candidate()` which calls `run_avahi_query()` for service browsing.

### Two paths forward:

**Option A**: Keep current approach (service advertisement enabled by default)
- Simple, works today
- Maintains backward compatibility
- No code changes needed beyond this fix

**Option B**: Implement true NSS-based discovery for Phase 3
- Change `discover_via_nss_and_api()` to use `getent hosts` directly
- Try predictable hostnames: `sugarkube0.local`, `sugarkube1.local`, etc.
- Only then can Phase 4 be safely enabled
- Requires significant refactoring and testing

## References

- Issue: Raspberry Pi 5 cluster setup logs showing discovery failure
- Roadmap: `notes/2025-11-14-mdns-discovery-fixes-and-simplification-roadmap.md`
- Fix commit: Changes default for `SUGARKUBE_SKIP_SERVICE_ADVERTISEMENT`
- Related outages:
  - `2025-11-14-api-readiness-401-rejection.json` (Phase 1 fix)
  - `2025-11-14-discovery-failopen-timeout-excessive.json` (Phase 1 fix)
  - `2025-11-14-avahi-restart-insufficient-stabilization.json` (Phase 1 fix)
