# mDNS Discovery Troubleshooting Guide

This guide helps diagnose and fix mDNS (multicast DNS) discovery issues when forming a k3s cluster.

## Quick Diagnosis

Run this on the **joining node** to see what's happening:

```bash
# Enable debug output
export SUGARKUBE_DEBUG=1

# Try discovery
avahi-browse --parsable --resolve _k3s-sugar-dev._tcp
# Let it run for 10 seconds, then press Ctrl+C
```

**Expected output:** You should see lines starting with `=` showing discovered services from other nodes.

**If you see nothing:** Jump to [No Services Discovered](#no-services-discovered).

---

## Integration test prerequisites

Running the Bats suites (for example,
`tests/integration/cluster_formation_e2e.bats`) with `AVAHI_AVAILABLE=1` relies on
host binaries instead of hermetic stubs. Confirm the following before running the
integration harness:

- `avahi-browse` and `avahi-publish` are installed (usually via `avahi-utils`).
- `getent hosts sugarkube0.local` (or another `.local` hostname) returns results, which
  confirms NSS is configured for mDNS. Install `libnss-mdns` and ensure
  `hosts: files mdns4_minimal [NOTFOUND=return] dns mdns4` appears in
  `/etc/nsswitch.conf` if lookups fail.

If these commands are missing on your development host, the integration suite will skip with
clear messages—installing the utilities or enabling NSS support lets the tests exercise the
discovery workflow end-to-end.

---

## Common Issues and Solutions

### No Services Discovered

**Symptom:** `avahi-browse` returns no results, or logs show:
```
[k3s-discover mdns] _load_lines_from_avahi: got 0 normalized lines from _k3s-sugar-dev._tcp
```

**Root Causes:**

1. **Bootstrap node hasn't published the service yet**
   - Wait for the bootstrap node's `just up dev` to complete fully
   - Check for log line: `event=mdns_publish outcome=ok`

2. **Multicast traffic is blocked**
   - Verify UDP port 5353 is allowed on your network/firewall
   - Check if nodes are on the same L2 subnet (multicast doesn't route)
   - Some WiFi routers block multicast by default (use Ethernet)

3. **Avahi daemon not running**
   ```bash
   sudo systemctl status avahi-daemon
   # Should show "active (running)"
   ```
   If not running: `sudo systemctl start avahi-daemon`

4. **NSS not configured for mDNS**
   ```bash
   grep mdns /etc/nsswitch.conf
   # Should show: hosts: files mdns4_minimal [NOTFOUND=return] dns mdns4
   ```
   If missing, run: `just prereqs` or manually configure nsswitch.conf

**Debug Steps:**

1. **Verify bootstrap node is advertising:**
   ```bash
   # On bootstrap node (e.g., sugarkube0)
   avahi-browse --all --terminate | grep k3s
   ```
   Should show `_k3s-sugar-dev._tcp` service.

2. **Test multicast connectivity:**
   ```bash
   # On joining node, capture mDNS traffic
   sudo tcpdump -i eth0 -n udp port 5353
   # Should see packets from other nodes' IP addresses
   ```

3. **Check Avahi service file exists:**
   ```bash
   # On bootstrap node
   ls -la /etc/avahi/services/
   # Should show k3s-sugar-dev*.service file
   ```

---

### Discovery Takes Too Long

**Symptom:** Discovery eventually works but takes 30+ seconds.

**Root Causes:**

1. **Network congestion or high latency**
   - mDNS uses multicast which is sensitive to network quality
   - Check for packet loss: `ping -c 100 <other-node>.local`

2. **Timeout too short for your network**
   - Default is 10 seconds
   - Increase: `export SUGARKUBE_MDNS_QUERY_TIMEOUT=30`

3. **Using `--terminate` flag (cache-only mode)**
   - This is no longer the default as of 2025-11-15
   - Verify: `echo $SUGARKUBE_MDNS_NO_TERMINATE` (should be "1" or empty)

---

### "service not found via avahi-browse after publish"

**Symptom:** Bootstrap node logs warning about not finding its own service.

**This is expected behavior** (as of 2025-11-15 fixes):
- The self-check uses a different avahi-browse command without `--terminate`
- The initial publish verification was using `--terminate` which only checks cache
- This warning can be safely ignored if the subsequent self-check succeeds:
  ```
  event=mdns_selfcheck outcome=ok
  ```

**If self-check also fails:**
- Wait a few seconds for Avahi to propagate the service
- Check Avahi daemon status: `sudo systemctl status avahi-daemon`
- Verify service file: `ls -la /etc/avahi/services/`

---

### TypeError: sequence item 0: expected str instance, bytes found

**Symptom:** Python traceback when trying to dump debug info.

**Status:** This was fixed on 2025-11-15. If you still see this:
1. Pull the latest code
2. Verify you have the fix: `grep "isinstance(line, bytes)" scripts/k3s_mdns_query.py`
3. If not present, the fix hasn't been applied yet

**Workaround:** The error doesn't affect functionality, just debug logging. You can ignore it.

---

## Environment Variables Reference

| Variable | Default | Purpose |
|----------|---------|---------|
| `SUGARKUBE_MDNS_NO_TERMINATE` | `1` | Skip `--terminate` flag to wait for network responses (recommended) |
| `SUGARKUBE_MDNS_QUERY_TIMEOUT` | `10.0` | Query timeout in seconds |
| `SUGARKUBE_DEBUG` | unset | Enable detailed debug logging |
| `SUGARKUBE_MDNS_WIRE_PROOF` | auto | Require TCP connection proof before joining |
| `ALLOW_IFACE` | unset | Pin avahi-browse to specific interface (e.g., `eth0`) |

---

## Understanding avahi-browse Flags

### `--terminate` (cache-only mode)

**What it does:** Exit immediately after dumping cached mDNS entries, without waiting for network responses.

**When to use:**
- Checking what's already known (fast lookups)
- Verifying services that have been running for a while

**When NOT to use:**
- Initial cluster formation (cache is empty)
- Discovering newly started services
- Troubleshooting discovery issues

**Current default:** NOT used (waits for network responses)

### `--resolve`

**What it does:** Resolve service records to get IP addresses and TXT records.

**Current default:** Used by default (we need IP addresses to join)

### `--ignore-local` (removed as of 2025-11-15)

**What it did:** Ignore services published by the local Avahi daemon.

**Why removed:**
- Prevented bootstrap nodes from verifying their own publications
- Unnecessary for cross-node discovery
- Nodes should be able to discover all k3s services, including their own

---

## Advanced Debugging

### Enable Full mDNS Debug Output

```bash
export SUGARKUBE_DEBUG=1
export SUGARKUBE_MDNS_WIRE_PROOF=1
export SAVE_DEBUG_LOGS=1
just up dev 2>&1 | tee mdns-debug.log
```

Look for these key log lines:

1. **Service publication:**
   ```
   event=mdns_publish outcome=ok
   ```

2. **Service discovery:**
   ```
   [k3s-discover mdns] _load_lines_from_avahi: got N normalized lines
   ```

3. **Server selection:**
   ```
   event=discover event=simple_discovery_found_servers count=N
   ```

### Check mDNS Packet Flow

```bash
# On joining node, watch for mDNS traffic
sudo tcpdump -i eth0 -vv -n udp port 5353

# Look for:
# - Queries going out (asking for _k3s-sugar-dev._tcp)
# - Responses coming in (from bootstrap node's IP)
```

### Verify Service Record Contents

```bash
# On bootstrap node
avahi-browse --all --resolve --terminate | grep -A10 k3s-sugar-dev

# Should show:
# - hostname: sugarkube0.local
# - address: <IP address>
# - port: 6443
# - TXT records: cluster=sugar, env=dev, role=server
```

---

## Known Issues and Fixes

### 2025-11-15: Discovery Fixes Applied

Three major issues were fixed:

1. **`--terminate` flag prevented discovery** - Now disabled by default
2. **`--ignore-local` flag blocked self-verification** - Removed entirely  
3. **TypeError in debug code** - Fixed bytes/str handling

If you're hitting discovery issues, make sure you have these fixes (commit 8da1010 or later).

### Related Outage Logs

- `outages/2025-11-15-mdns-terminate-flag-prevented-discovery.json`
- `outages/2025-11-15-mdns-ignore-local-blocked-verification.json`
- `outages/2025-11-15-mdns-timeout-bytes-str-mismatch.json`

---

## Still Stuck?

If you've tried everything above and discovery still fails:

1. **Collect diagnostic bundle:**
   ```bash
   export SUGARKUBE_DEBUG=1
   export SAVE_DEBUG_LOGS=1
   just up dev
   
   # Logs will be in logs/up/
   ```

2. **Verify network basics:**
   ```bash
   # Can nodes ping each other?
   ping -c 5 sugarkube0.local
   
   # Can nodes resolve .local names?
   avahi-resolve -n sugarkube0.local
   ```

3. **Check for common misconfigurations:**
   - Both nodes on same subnet? `ip addr show`
   - Firewall blocking multicast? `sudo iptables -L -n`
   - Correct environment? `echo $SUGARKUBE_ENV`
   - Token set correctly? `echo $SUGARKUBE_TOKEN_DEV` (should be `K10...`)

4. **File an issue** with:
   - Debug logs from both nodes
   - Output of `avahi-browse --all`
   - Network configuration (`ip addr`, `ip route`)
   - Avahi configuration (`cat /etc/avahi/avahi-daemon.conf`)
