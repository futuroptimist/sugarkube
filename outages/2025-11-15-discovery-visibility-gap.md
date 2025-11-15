# Outage Report: mDNS Discovery Visibility Gap

**Date**: 2025-11-15  
**Component**: k3s-discover.sh mDNS discovery  
**Severity**: High (cluster formation blocked)  
**Status**: Under Investigation

## Summary

Real-world testing on Raspberry Pi 5 hardware revealed that joining nodes (sugarkube1) cannot discover bootstrap nodes (sugarkube0) via mDNS service browsing, despite:
- Phase 3/4 defaults being compatible (service advertisement enabled by default)
- Bootstrap node successfully publishing mDNS service
- Self-checks confirming service is resolvable locally
- Both nodes on the same LAN segment

## Timeline

### sugarkube0 (Bootstrap Node)
```
18:37:17  Discovery starts (no token, bootstrap allowed)
18:41:24  Simple discovery finds no servers (expected - first node)
18:41:24  Begins bootstrap process
18:41:57  mDNS service published (bootstrap role)
18:42:04  Self-check confirms service visible locally
18:42:30  k3s API becomes ready (401 status)
18:43:04  mDNS service republished (server role)
18:43:09  Self-check confirms server service visible
```

### sugarkube1 (Joining Node)
```
18:45:35  Discovery starts (token present, cannot bootstrap)
18:45:35  Simple discovery enabled
18:45:35  Service browse begins with 30s timeout
18:49:42  Discovery fails after ~4 minutes
18:49:42  Error: "No joinable servers found via mDNS service browsing"
18:49:42  Exit: Cannot bootstrap (token present but no servers)
```

## Observed Behavior

### What Worked
1. ✅ sugarkube0 bootstrapped successfully
2. ✅ Service published to Avahi
3. ✅ Local self-check passed (mdns_selfcheck confirmed service visible)
4. ✅ avahi-resolve confirmed host record exists

### What Failed
1. ❌ sugarkube1 could not discover sugarkube0 via `avahi-browse`
2. ❌ Discovery ran for ~4 minutes despite 30s timeout
3. ❌ No debug output explaining why browse returned empty

## Root Cause Analysis

### Hypothesis 1: avahi-browse Not Waiting for Network Responses
**Evidence**:
- Discovery timeout set to 30s
- SUGARKUBE_MDNS_NO_TERMINATE=1 should skip `--terminate` flag
- But browse may still be using cached results only

**Test**: Verify avahi-browse command actually omits `--terminate` flag

### Hypothesis 2: Service Not Propagating Across Network
**Evidence**:
- Service confirmed visible locally (self-check passed)
- sugarkube1 on same network but cannot see service
- May indicate mDNS reflector or network bridge issues

**Test**: Manual `avahi-browse` from sugarkube1 to see if service appears

### Hypothesis 3: Network Segmentation or Firewall
**Evidence**:
- mDNS uses UDP port 5353 multicast (224.0.0.251)
- Some switches/routers block multicast by default
- Raspberry Pi firmware/network config may filter mDNS

**Test**: Run `tcpdump -i any udp port 5353` during service browse

### Hypothesis 4: Timing Issue - Service Not Yet Visible
**Evidence**:
- sugarkube0 published service at 18:42:30 (bootstrap)
- sugarkube0 republished at 18:43:04 (server)
- sugarkube1 started browsing at 18:45:35 (3+ minutes later)
- Should be plenty of time for mDNS to propagate

**Unlikely**: Time gap is sufficient for propagation

### Hypothesis 5: Service Type Mismatch
**Evidence**:
- Bootstrap publishes `_k3s-sugar-dev._tcp` with `role=bootstrap`
- Server republishes `_k3s-sugar-dev._tcp` with `role=server`
- Browse queries for `_k3s-sugar-dev._tcp`
- Service type matches, so this is not the issue

**Unlikely**: Service types align correctly

## Diagnostic Logging Added

To help identify the exact failure mode, we added extensive debug logging:

### k3s-discover.sh Changes
1. **Discovery configuration logging**:
   ```bash
   log_info discover event=simple_discovery_config \
     no_terminate="${SUGARKUBE_MDNS_NO_TERMINATE}" \
     timeout="${SUGARKUBE_MDNS_QUERY_TIMEOUT}" \
     service_type="_k3s-${CLUSTER}-${ENVIRONMENT}._tcp" \
     debug_enabled="${SUGARKUBE_DEBUG:-0}"
   ```

2. **select_server_candidate logging**:
   - Log when query starts
   - Log raw selection line from avahi-browse
   - Log when no results found

3. **Post-publish verification**:
   ```bash
   # After service published, verify it's browsable
   browse_verification="$(SUGARKUBE_DEBUG=1 run_avahi_query server-select ...)"
   ```

### k3s_mdns_query.py Changes
1. **query_mdns entry logging**:
   - Log mode, cluster, environment
   - Log service types being queried
   - Log timeout and no_terminate settings
   - Log number of results at each stage

2. **_load_lines_from_avahi logging**:
   - Log which service type being browsed
   - Log number of normalized lines returned

3. **_invoke_avahi logging**:
   - Log exact avahi-browse command being executed
   - Log timeout value
   - Log exit code and stderr
   - Log first 10 lines of stdout for inspection

4. **Result logging**:
   - Log number of final results
   - Log first 5 results for inspection

### Debug Activation
Debug logging is now automatically enabled during simple discovery when `SAVE_DEBUG_LOGS=1` is set (which is already the case in the test logs we're examining).

## Resolution Steps

### Immediate (Completed)
1. ✅ Added comprehensive debug logging
2. ✅ Created e2e test suite (`tests/integration/cluster_formation_e2e.bats`)
3. ✅ Documented findings in this outage report

### Next Steps
1. **Re-run test with debug logging**:
   ```bash
   export SAVE_DEBUG_LOGS=1
   export SAVE_DEBUG_LOGS_DIR=logs/up
   just up dev  # On sugarkube0
   just up dev  # On sugarkube1
   ```

2. **Analyze new logs** for:
   - Exact avahi-browse command being executed
   - Whether --terminate is present or absent
   - Raw avahi-browse output (empty? error?)
   - Parse errors or format issues
   - Timeout behavior (did it actually wait 30s?)

3. **Manual verification** on sugarkube1:
   ```bash
   # Test basic mDNS resolution
   avahi-browse --parsable --resolve _k3s-sugar-dev._tcp
   
   # Test without --terminate (wait for network)
   timeout 30 avahi-browse --parsable --resolve _k3s-sugar-dev._tcp
   
   # Check if host is resolvable
   getent hosts sugarkube0.local
   avahi-resolve --name sugarkube0.local
   
   # Check for mDNS traffic
   sudo tcpdump -i any udp port 5353 -n
   ```

4. **Network diagnostics**:
   ```bash
   # On sugarkube0: verify service is advertised
   avahi-browse --all
   
   # Check Avahi daemon status
   systemctl status avahi-daemon
   journalctl -u avahi-daemon -n 100
   
   # Verify mDNS responder is listening
   sudo netstat -uln | grep 5353
   sudo ss -ulnp | grep 5353
   ```

5. **If still failing, add packet capture**:
   - Capture mDNS traffic during discovery
   - Verify queries are being sent
   - Verify responses are being received
   - Check for TTL or network hop issues

## E2E Test Coverage

Created `tests/integration/cluster_formation_e2e.bats` with tests for:

1. **Phase 1: Bootstrap node without token publishes service**
   - Verifies service is browsable after publish
   - Uses k3s_mdns_query to discover service

2. **Phase 2: Joining node with token discovers bootstrap node**
   - Simulates second node discovery
   - Verifies MDNS_NO_TERMINATE=1 behavior
   - Checks that discovery succeeds

3. **Phase 3: Multiple nodes can discover the bootstrap node**
   - Tests concurrent discovery from multiple "nodes"
   - Verifies service remains discoverable

4. **MDNS_NO_TERMINATE flag behavior**
   - Verifies --terminate vs no --terminate behavior
   - Ensures we actually wait for network responses

5. **Discovery timeout behavior**
   - Verifies discovery doesn't hang forever
   - Checks timeout is respected

## Related Issues

- **2025-11-15-phase3-phase4-incompatibility.md**: Fixed defaults, but real discovery still failing
- **2025-11-14-mdns-discovery-hardcoded-hostnames.md**: Removed hardcoded hostname iteration
- **2025-11-14-mdns-complexity-analysis.md**: Background on simplification roadmap

## Lessons Learned

1. **Self-checks are not sufficient**: A service passing local self-checks doesn't guarantee network-wide discoverability

2. **Need real-world testing**: Unit tests and mocked tests didn't catch this issue; actual Pi hardware revealed the problem

3. **Debug logging is essential**: Without detailed logging of avahi-browse execution, we have no visibility into why discovery fails

4. **E2E tests must exercise real workflow**: Tests must simulate the actual deployment steps users follow

## Prevention

1. ✅ Added debug logging to capture failure modes
2. ✅ Created e2e tests that mirror docs/raspi_cluster_setup.md workflow
3. 🔄 Next: Run e2e tests in CI with real Avahi daemon
4. 🔄 Next: Add network capture to diagnostic bundle
5. 🔄 Next: Document expected mDNS packet patterns

## Open Questions

1. Why does avahi-browse on sugarkube1 not see the service?
2. Is mDNS multicast traffic being blocked?
3. Is there a timing issue we're missing?
4. Does the MDNS_NO_TERMINATE flag actually work as expected?
5. Are there Avahi daemon differences between Pi 4 and Pi 5?

## References

- Original logs: `logs/up/20251115T023707Z_ecd5c60_sugarkube0_just-up-dev.log`
- Original logs: `logs/up/20251115T024530Z_6c1c7a4_sugarkube1_just-up-dev.log`
- Documentation: `docs/raspi_cluster_setup.md`
- Discovery script: `scripts/k3s-discover.sh`
- Query helper: `scripts/k3s_mdns_query.py`
- E2E tests: `tests/integration/cluster_formation_e2e.bats`
