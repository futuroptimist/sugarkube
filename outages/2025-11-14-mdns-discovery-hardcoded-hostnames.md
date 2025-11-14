# Outage Report: mDNS Discovery Hardcoded Hostnames Antipattern

**Date**: 2025-11-14  
**Component**: k3s-discover.sh simple discovery  
**Severity**: High  
**Status**: Resolved

## Summary

Recent simplification PRs (Phase 2-4) introduced an antipattern where mDNS discovery logic was replaced with hardcoded hostname iteration (`sugarkube0.local`, `sugarkube1.local`, `sugarkube2.local`). This enforced a specific naming convention and prevented the discovery of k3s nodes with different hostnames, breaking the fundamental design principle of network-based service discovery.

## Impact

### Affected Users
- Any deployment using non-standard hostnames for Raspberry Pi nodes
- Clusters where nodes are named differently than the sugarkube{N} pattern
- Environments requiring flexible node naming for organizational or infrastructure reasons

### Observable Behavior

From the problem statement logs:
```
ts=2025-11-14T15:03:28-08:00 level=info event=discover event=simple_discovery_try candidate=sugarkube0.local idx=0
ts=2025-11-14T15:03:28-08:00 level=info event=discover event=simple_discovery_resolved candidate=sugarkube0.local
ts=2025-11-14T15:05:29-08:00 level=info event=apiready outcome=timeout host="sugarkube0.local" port="6443" attempts=61 elapsed=121
ts=2025-11-14T15:05:29-08:00 level=info event=discover event=simple_discovery_api_fail candidate=sugarkube0.local
ts=2025-11-14T15:05:29-08:00 level=info event=discover event=simple_discovery_try candidate=sugarkube1.local idx=1
```

The system was explicitly looking for `sugarkube0.local`, `sugarkube1.local`, and `sugarkube2.local` instead of scanning the local network for any available k3s nodes advertising themselves via mDNS.

## Root Cause

### Timeline

The simplification effort aimed to reduce complexity in the discovery process by:
1. Skipping the leader election process (valid simplification)
2. Skipping the absence gate checks (valid simplification)
3. Replacing mDNS service browsing with direct hostname lookups (**invalid antipattern**)

### Technical Details

Two functions were affected:

1. **`discover_via_nss_and_api()` (lines 4583-4636)**:
   - Iterated through `sugarkube{0..N}.local` hostnames based on `SUGARKUBE_SERVERS` count
   - Used `getent hosts` to resolve each hardcoded hostname
   - Never used `avahi-browse` to discover advertised services

2. **`try_discovery_failopen()` (lines 4428-4487)**:
   - Same antipattern in the fail-open path
   - Tried hardcoded `sugarkube{0..N}.local` hostnames sequentially

### Why This Was Wrong

The correct approach in mDNS-based service discovery is:
- **Browse for services**: Use `avahi-browse` to find all nodes advertising the k3s service
- **Service records contain hostnames**: The service advertisement includes the actual hostname
- **No assumptions**: Don't assume what nodes are named

The existing infrastructure already provided this via:
- `run_avahi_query server-select`: Browses for k3s services and selects a candidate
- `select_server_candidate()`: Wrapper that calls the query and parses results
- `k3s_mdns_parser.py`: Python helper that parses `avahi-browse` output

## Resolution

### Changes Made

1. **Restored proper service browsing in `discover_via_nss_and_api()`**:
   - Now calls `select_server_candidate()` to browse for advertised k3s services
   - Discovers nodes regardless of their hostname
   - Still maintains the simplified flow (no leader election)

2. **Fixed fail-open discovery in `try_discovery_failopen()`**:
   - Now uses `select_server_candidate()` with retry logic
   - Properly discovers services instead of assuming hostnames
   - Added retry mechanism since mDNS can be flaky

3. **Updated documentation**:
   - Corrected comment at line 196-198 to accurately describe behavior
   - Changed from "direct NSS resolution instead of service browsing" to "mDNS service browsing without leader election"

### Code Changes

```bash
# Before (antipattern):
for idx in $(seq 0 $((server_count - 1))); do
  local candidate="sugarkube${idx}.local"
  if getent hosts "${candidate}" >/dev/null 2>&1; then
    if wait_for_remote_api_ready "${candidate}" "" 6443; then
      # found a server
    fi
  fi
done

# After (proper service discovery):
if select_server_candidate; then
  local server="${MDNS_SELECTED_HOST}"
  if wait_for_remote_api_ready "${server}" "${MDNS_SELECTED_IP:-}" "${MDNS_SELECTED_PORT:-6443}"; then
    # found a server
  fi
fi
```

## Prevention

### Design Principles Reaffirmed

1. **Service Discovery over Hostname Assumptions**: Always use mDNS service browsing to discover nodes; never hardcode hostname patterns
2. **Separation of Concerns**: Simplification should focus on process flow (e.g., skipping leader election) not on bypassing service discovery mechanisms
3. **Zero-Configuration Networking**: Nodes should be discoverable by their advertised services, not by naming conventions

### Testing Recommendations

1. Test discovery with non-standard hostnames (e.g., `pi-node-1.local`, `cluster-a.local`)
2. Test with mixed hostname patterns in the same cluster
3. Verify service browsing works when nodes use organizational naming schemes

### Review Checklist

When reviewing PRs that touch discovery logic:
- [ ] Does it use `avahi-browse` or equivalent service browsing?
- [ ] Does it make assumptions about node hostnames?
- [ ] Does it iterate through hardcoded hostname patterns?
- [ ] Are there tests with non-standard hostnames?

## References

- Problem statement logs showing hardcoded hostname iteration
- `scripts/k3s-discover.sh` lines 196-198, 4583-4636, 4428-4487
- `docs/raspi_cluster_setup.md` describing the quick start process
- Existing service browsing infrastructure: `run_avahi_query`, `select_server_candidate()`
