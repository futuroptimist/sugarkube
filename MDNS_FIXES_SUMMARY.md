# mDNS Discovery Fixes Summary

**Date:** 2025-11-15  
**Branch:** copilot/setup-k3s-cluster  
**Status:** ✅ Complete - Ready for Testing

## Problem Statement

k3s nodes on the same local network (sugarkube0 and sugarkube1) could not discover each other during initial cluster formation using `just up dev`. Both nodes had:
- Same subnet
- mDNS hostnames (sugarkube0.local, sugarkube1.local)
- Correct token configuration
- No firewall blocking between them

Yet discovery consistently failed with "No joinable servers found via mDNS service browsing".

## Root Causes Discovered

### 1. Primary Issue: `--terminate` Flag (CRITICAL)

**What was wrong:**
- `avahi-browse --terminate` was being used by default
- This flag tells avahi-browse to only dump cached entries and exit immediately
- On fresh boot or first discovery, the mDNS cache is empty
- Result: 0 services discovered, even though they were being advertised

**The fix:**
- Changed `SUGARKUBE_MDNS_NO_TERMINATE` default from "0" to "1"
- Now avahi-browse waits for actual mDNS multicast responses
- Can still enable fast cache-only mode with `SUGARKUBE_MDNS_NO_TERMINATE=0`

**Evidence:**
```
[k3s-discover mdns] avahi-browse attempt 1: exit_code=0
[k3s-discover mdns] _load_lines_from_avahi: got 0 normalized lines from _k3s-sugar-dev._tcp
```

### 2. Secondary Issue: `--ignore-local` Flag

**What was wrong:**
- `avahi-browse --ignore-local` was being added for server discovery
- This prevented bootstrap nodes from verifying their own service publications
- Caused "service not found via avahi-browse after publish" warnings
- Unnecessary - nodes should discover ALL k3s services on the network

**The fix:**
- Removed `--ignore-local` flag entirely
- Nodes can now discover any k3s service, including their own
- Self-verification works properly

### 3. Tertiary Issue: TypeError in Debug Code

**What was wrong:**
- When `subprocess.TimeoutExpired` occurred, stdout/stderr contained bytes
- Code tried to join bytes with strings: `"\n".join(lines)`
- Crashed with: `TypeError: sequence item 0: expected str instance, bytes found`

**The fix:**
- Added defensive bytes-to-str conversion in exception handler
- Added defensive conversion in debug dump code
- Now handles both bytes and str gracefully

## Changes Made

### Code Changes

**scripts/k3s_mdns_query.py:**
1. Line 58: Inverted terminate logic (default to wait for network)
2. Lines 62-68: Removed --ignore-local flag
3. Lines 257-266: Fixed bytes handling in TimeoutExpired
4. Lines 535-547: Fixed bytes handling in debug dump
5. Lines 1-38: Enhanced module docstring

### Tests Added

**tests/scripts/test_mdns_discovery_regression.py** (170 lines):
- `test_terminate_flag_not_used_by_default` - Ensures default waits for network
- `test_terminate_flag_can_be_enabled_explicitly` - Verifies override works
- `test_ignore_local_flag_not_used` - Ensures flag stays removed
- `test_timeout_exception_handles_bytes` - Prevents TypeError regression
- `test_debug_dump_handles_mixed_bytes_and_str` - Defensive test
- `test_env_variable_documentation` - Documents expected behavior

### Documentation Added

**docs/mdns_troubleshooting.md** (300 lines):
- Quick diagnosis section
- Common issues with solutions
- Advanced debugging techniques
- Environment variables reference
- Known issues and fixes

**docs/raspi_cluster_setup.md** (60 lines changed):
- Technical details: mDNS service browsing
- Enhanced troubleshooting section
- New environment variables in config table

**outages/** (3 new files):
- 2025-11-15-mdns-terminate-flag-prevented-discovery.json
- 2025-11-15-mdns-ignore-local-blocked-verification.json
- 2025-11-15-mdns-timeout-bytes-str-mismatch.json

## Testing Results

### Unit Tests
```
17/17 tests PASSED
- 11 existing tests (test_k3s_mdns_query.py)
- 6 new regression tests (test_mdns_discovery_regression.py)
```

### Security Scan
```
CodeQL: 0 alerts
- python: No alerts found
```

## How to Test on Real Hardware

### Bootstrap First Node

```bash
# On sugarkube0
just wipe
export SUGARKUBE_SERVERS=3
export SAVE_DEBUG_LOGS=1
just up dev

# After completion, get the token
sudo cat /var/lib/rancher/k3s/server/node-token
```

### Join Second Node

```bash
# On sugarkube1
just wipe
export SUGARKUBE_SERVERS=3
export SAVE_DEBUG_LOGS=1
export SUGARKUBE_TOKEN_DEV="<token from sugarkube0>"
just up dev
```

### Expected Behavior

**sugarkube0 logs should show:**
- ✅ `event=mdns_publish outcome=ok`
- ✅ `event=mdns_selfcheck outcome=ok`
- ✅ No "service not found via avahi-browse" errors (or they're quickly resolved)

**sugarkube1 logs should show:**
- ✅ `[k3s-discover mdns] _load_lines_from_avahi: got N normalized lines` (N > 0)
- ✅ `event=discover event=simple_discovery_found_servers count=1`
- ✅ Node successfully joins cluster
- ✅ No TypeError crashes

### Verification Commands

```bash
# On either node, check cluster status
kubectl get nodes

# Should show both sugarkube0 and sugarkube1 as Ready

# Verify mDNS is working
avahi-browse --all --resolve | grep k3s-sugar-dev
# Should show services from both nodes
```

## Troubleshooting

If discovery still fails after these fixes:

1. **Verify multicast connectivity:**
   ```bash
   sudo tcpdump -i eth0 -n udp port 5353
   # Should see packets from other node's IP
   ```

2. **Check Avahi daemon:**
   ```bash
   sudo systemctl status avahi-daemon
   # Should be active (running)
   ```

3. **Enable debug logging:**
   ```bash
   export SUGARKUBE_DEBUG=1
   export SUGARKUBE_MDNS_WIRE_PROOF=1
   just up dev 2>&1 | tee debug.log
   ```

4. **Read the troubleshooting guide:**
   - `docs/mdns_troubleshooting.md` - comprehensive guide
   - Check common issues section
   - Review environment variables

## Impact

These fixes enable:
- ✅ Zero-configuration k3s cluster formation
- ✅ Discovery with any hostname pattern
- ✅ Reliable initial cluster bootstrapping
- ✅ Self-verification of service publications
- ✅ Better debugging when issues occur

## Next Steps

1. Test on real Raspberry Pi hardware
2. Verify logs show successful discovery
3. Form 2-3 node clusters successfully
4. Document any remaining edge cases

## Related Files

- Fix commit: `8da1010` and `20317d5`
- Main code: `scripts/k3s_mdns_query.py`
- Tests: `tests/scripts/test_mdns_discovery_regression.py`
- Docs: `docs/mdns_troubleshooting.md`
- Outages: `outages/2025-11-15-*.json`
