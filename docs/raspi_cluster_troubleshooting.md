---
personas:
  - hardware
  - software
---

# Raspberry Pi Cluster Troubleshooting Guide

This guide helps you diagnose and fix common issues when forming and operating your Raspberry Pi k3s cluster. It focuses on interpreting logs saved by `SAVE_DEBUG_LOGS=1` and sanitized mDNS debug output.

**Related docs:**
- [Raspberry Pi Cluster Setup (Quick Start)](raspi_cluster_setup.md) — How to bring up your cluster
- [Raspberry Pi Cluster Operations](raspi_cluster_operations.md) — Day-two operations and log capture
- [mDNS Troubleshooting Guide](mdns_troubleshooting.md) — Deep dive into mDNS-specific issues

## Understanding Your Logs

Sugarkube provides several types of logs to help you debug cluster issues:

### Up Logs (`logs/up/*.log`)

These are timestamped logs of cluster bring-up operations, created when you run:
```bash
just save-logs env=dev
# or
SAVE_DEBUG_LOGS=1 just up dev
```

**What's in them:**
- Timestamped events with structured fields (e.g., `ts=`, `level=`, `event=`)
- Discovery process: mDNS queries, leader election, server selection
- Installation steps: k3s download, service start, API readiness checks
- Network diagnostics: Avahi status, multicast checks, port connectivity
- **Sanitized data:** External IPs, secrets, and tokens are automatically redacted as `[REDACTED_IP]` or `[REDACTED_SECRET]`

**Location:** `logs/up/<timestamp>_<commit>_<hostname>_just-up-<env>.log`

**Key log patterns to recognize:**
- `event=discover` — Discovery phase events
- `event=mdns_publish` — Service advertisement publishing
- `ms_elapsed=` — Timing metrics (values under 200ms are normal)
- `outcome=ok` — Successful operation
- `outcome=timeout` — Operation exceeded timeout
- `level=info` — Normal informational message
- `severity=warn` — Warning that may need attention

### Sanitized mDNS Debug Logs (`logs/debug-mdns*.log.sanitized`)

Created by running `logs/debug-mdns.sh`, these capture detailed mDNS traffic and Avahi interactions with sensitive data redacted.

**What's in them:**
- Avahi daemon status and configuration
- mDNS service browsing output (`avahi-browse` results)
- Multicast traffic captures (UDP port 5353)
- Service advertisement verification
- **Sanitized data:** MAC addresses and external IPs are redacted

**When to use:** For deep debugging of mDNS discovery issues when standard logs don't reveal the problem.

---

## Common Failure Scenarios

### Scenario 1: Second Node Cannot Join Cluster

**Symptom:**
When running `just up dev` on the second node (after successfully bootstrapping the first), the node fails to join and you see one of these errors:
- "No joinable servers found via mDNS service browsing"
- "SUGARKUBE_TOKEN (or per-env variant) required"
- Discovery succeeds but k3s never starts or times out

**Which logs to inspect:**

1. **On the joining node** — Check the most recent log in `logs/up/`:
   ```bash
   ls -lt logs/up/ | head -1
   cat logs/up/<latest-log-file>
   ```

2. **On the bootstrap node** — Verify it successfully published its service:
   ```bash
   # Look for recent bootstrap logs
   ls -lt logs/up/ | head -1
   cat logs/up/<bootstrap-log-file> | grep mdns_publish
   ```

**Example log patterns to look for:**

**Joining node showing discovery failure:**
```
event=discover event=simple_discovery_found_servers count=0
```
This means no k3s servers were found via mDNS.

**Joining node showing missing token:**
```
event=token_resolution token_present=0 allow_bootstrap=0
```
The node tried to join but no token was provided.

**Bootstrap node showing successful service publication:**
```
event=mdns_publish outcome=ok
event=mdns_selfcheck outcome=ok
```
The bootstrap node successfully advertised its k3s API.

**Next steps:**

1. **If no servers found (count=0):**
   - Verify the bootstrap node is running: `ssh sugarkube0 'sudo systemctl status k3s'`
   - Check that both nodes are on the same L2 subnet: `ip addr show`
   - Test multicast connectivity: See [mDNS Troubleshooting Guide](mdns_troubleshooting.md#no-services-discovered)
   - Verify Avahi is running on both nodes: `sudo systemctl status avahi-daemon`
   - On the bootstrap node, confirm service is advertised: `avahi-browse --all --terminate | grep k3s`

2. **If token_present=0:**
   - Retrieve the token from the bootstrap node:
     ```bash
     ssh sugarkube0 'sudo cat /var/lib/rancher/k3s/server/node-token'
     # or use the helper:
     ssh sugarkube0 'just cat-node-token'
     ```
   - Export it on the joining node before retrying:
     ```bash
     export SUGARKUBE_TOKEN_DEV="K10abc123..."  # paste the token here
     export SUGARKUBE_SERVERS=3
     just up dev
     ```

3. **If discovery succeeds but k3s fails to start:**
   - Check k3s service logs on the joining node: `sudo journalctl -u k3s -n 100`
   - Look for certificate errors: `sudo journalctl -u k3s | grep -i "certificate\|tls\|x509"`
   - Verify the node can reach the API: `curl -k https://sugarkube0.local:6443/livez`

---

### Scenario 2: mDNS Discovery Issues

**Symptom:**
Discovery takes too long (30+ seconds), times out, or returns inconsistent results. You may see repeated discovery attempts or warnings about absence gates.

**Which logs to inspect:**

1. **Up logs** showing discovery timing:
   ```bash
   cat logs/up/<log-file> | grep -E "ms_elapsed|event=discover"
   ```

2. **mDNS wire-level diagnostics:**
   ```bash
   export SUGARKUBE_DEBUG=1
   export SUGARKUBE_MDNS_WIRE_PROOF=1
   just save-logs env=dev
   ```

**Example log patterns to look for:**

**Slow discovery (high latency):**
```
event=discover event=simple_discovery_found_servers count=1 ms_elapsed=25400
```
Discovery took 25+ seconds (normal is under 200ms).

**Discovery timeout:**
```
event=discover msg="mDNS absence gate timed out" severity=warn mdns_absence_confirmed=0 ms_elapsed=21308
```
The absence gate couldn't confirm the old service was gone before timeout.

**Avahi D-Bus communication failure:**
```
event=avahi_dbus_ready outcome=timeout bus_status=call_failed
```
Communication with Avahi daemon via D-Bus failed.

**Discovery found zero results repeatedly:**
```
DEBUG: query_mdns returned 0 results: []
```
Multiple discovery attempts found no advertised services.

**Next steps:**

1. **For slow discovery (>1000ms but eventually works):**
   - Increase the timeout: `export SUGARKUBE_MDNS_QUERY_TIMEOUT=30`
   - Check network quality: `ping -c 100 sugarkube0.local` (look for packet loss)
   - Look for multicast congestion: Is the LAN busy with other mDNS devices?

2. **For discovery timeout or zero results:**
   - Verify multicast is allowed: `sudo tcpdump -i eth0 -n udp port 5353`
   - Check Avahi configuration: `cat /etc/avahi/avahi-daemon.conf`
   - Verify nsswitch.conf includes mDNS: `grep mdns /etc/nsswitch.conf`
   - Test service browsing manually: `avahi-browse --all --resolve | grep k3s`
   - See the detailed [mDNS Troubleshooting Guide](mdns_troubleshooting.md) for more diagnostics

3. **For Avahi D-Bus failures:**
   - Restart Avahi: `sudo systemctl restart avahi-daemon`
   - Wait 5-10 seconds for the daemon to fully initialize
   - Fall back to CLI mode if needed: `export SUGARKUBE_MDNS_DBUS=0`

4. **For persistent issues:**
   - Capture full mDNS debug output: `./logs/debug-mdns.sh`
   - Review sanitized output in `logs/debug-mdns_<timestamp>.log.sanitized`
   - Check for network policy or firewall blocking UDP 5353

---

### Scenario 3: Missing or Incorrect Node Token

**Symptom:**
Node tries to bootstrap a new cluster instead of joining the existing one, or authentication fails with "unauthorized" or "invalid token" errors.

**Which logs to inspect:**

1. **Up logs showing token resolution:**
   ```bash
   cat logs/up/<log-file> | grep token_resolution
   ```

2. **k3s service logs if join was attempted:**
   ```bash
   sudo journalctl -u k3s -n 50 | grep -i "token\|unauthorized\|auth"
   ```

**Example log patterns to look for:**

**No token provided (will bootstrap):**
```
event=token_resolution token_present=0 allow_bootstrap=1 node_token_state=missing boot_token_state=missing
```
The node has no token and will create a new cluster instead of joining.

**Token provided (will join):**
```
event=token_resolution token_present=1 allow_bootstrap=0 node_token_state=missing boot_token_state=missing
```
The environment variable `SUGARKUBE_TOKEN_DEV` is set.

**k3s authentication failure:**
```
k3s[...]: Failed to register node: Unauthorized
k3s[...]: invalid token
```
The token doesn't match the bootstrap node's token.

**Next steps:**

1. **If the node accidentally bootstrapped:**
   - Wipe the node: `just wipe`
   - Source the cleanup script to clear environment variables:
     ```bash
     source "${XDG_CACHE_HOME:-$HOME/.cache}/sugarkube/wipe-env.sh"
     ```
   - Get the correct token from the first node:
     ```bash
     ssh sugarkube0 'just cat-node-token'
     ```
   - Export the token and retry:
     ```bash
     export SUGARKUBE_TOKEN_DEV="K10abc123..."
     export SUGARKUBE_SERVERS=3
     just up dev
     ```

2. **If token is incorrect or outdated:**
   - Verify the token on the bootstrap node:
     ```bash
     ssh sugarkube0 'sudo cat /var/lib/rancher/k3s/server/node-token'
     ```
   - Compare with what you exported: `echo $SUGARKUBE_TOKEN_DEV`
   - Update the token if they don't match (token should start with `K10` and be ~60+ characters)
   - Re-export and retry: `export SUGARKUBE_TOKEN_DEV="<correct-token>"`

3. **If token file is missing on bootstrap node:**
   - Check if k3s is running: `sudo systemctl status k3s`
   - If not running, bootstrap failed — check: `sudo journalctl -u k3s -n 100`
   - If running but token file missing, it may be an agent (not server):
     ```bash
     sudo k3s kubectl get nodes -o wide
     # Check role column for "control-plane" vs "worker"
     ```

---

### Scenario 4: k3s Service Fails to Start or Never Becomes Ready

**Symptom:**
Discovery succeeds and k3s installs, but the k3s service never reaches a healthy state. You see timeouts like "API never became ready after 120s" or the service crashes repeatedly.

**Which logs to inspect:**

1. **Up logs showing the failure:**
   ```bash
   cat logs/up/<log-file> | grep -E "event=install|event=wait"
   ```

2. **k3s service logs (most important):**
   ```bash
   sudo journalctl -u k3s -n 100 --no-pager
   ```

3. **k3s logs filtered for common errors:**
   ```bash
   # Certificate/TLS errors
   sudo journalctl -u k3s | grep -i "certificate\|tls\|x509" | tail -20
   
   # Connection errors
   sudo journalctl -u k3s | grep -i "connection\|refused\|timeout" | tail -20
   
   # etcd errors (for HA clusters)
   sudo journalctl -u k3s | grep -i "etcd\|raft" | tail -20
   ```

**Example log patterns to look for:**

**In up logs - API readiness timeout:**
```
ts=2025-11-10T06:32:15-08:00 level=error event=install msg="API never became ready" timeout_seconds=120
```

**In k3s logs - Certificate validation failure:**
```
x509: certificate is valid for sugarkube0.local, not 192.168.1.100
```
The API certificate doesn't include the IP address the node is trying to use.

**In k3s logs - Connection refused:**
```
Failed to connect to server https://sugarkube0.local:6443: dial tcp 192.168.1.100:6443: connect: connection refused
```
The k3s API on the remote server isn't responding.

**In k3s logs - etcd cluster join failure:**
```
failed to join etcd cluster: context deadline exceeded
error validating server configuration: can not perform etcd operations
```
The node can't join the etcd cluster (usually networking or certificate issue).

**Next steps:**

1. **Verify basic connectivity to the API:**
   ```bash
   # From the problem node, test the API endpoint
   curl -k https://sugarkube0.local:6443/livez
   # Should return HTTP 401 or 200 (both mean API is alive)
   ```

2. **Check k3s service configuration:**
   ```bash
   # Check what server URL k3s is using
   grep K3S_URL /etc/systemd/system/k3s.service.env
   
   # Check that token is set
   grep K3S_TOKEN /etc/systemd/system/k3s.service.env | wc -c
   # Should show >50 characters if token is present
   ```

3. **Verify certificate includes required SANs:**
   ```bash
   # On bootstrap node, check certificate SANs
   openssl s_client -connect localhost:6443 </dev/null 2>/dev/null | \
     openssl x509 -text | grep -A1 "Subject Alternative Name"
   # Should include hostnames AND IP addresses
   ```

4. **Check etcd health (HA clusters only):**
   ```bash
   # On bootstrap node
   sudo k3s etcd-snapshot save --name diagnostic
   sudo k3s etcd-snapshot ls
   ```

5. **Verify time synchronization:**
   ```bash
   # etcd requires clocks within 500ms
   timedatectl status
   # or
   chronyc tracking
   ```
   If clock drift is too large, see [Scenario 5: Time Synchronization Issues](#scenario-5-time-synchronization-issues).

6. **Check network ports are reachable:**
   ```bash
   # From joining node, test connectivity to bootstrap node
   nc -zv sugarkube0.local 6443  # k3s API
   nc -zv sugarkube0.local 2379  # etcd client (HA only)
   nc -zv sugarkube0.local 2380  # etcd peer (HA only)
   ```

7. **Restart k3s if configuration looks correct:**
   ```bash
   sudo systemctl restart k3s
   sudo journalctl -u k3s -f  # Watch logs in real-time
   ```

8. **If nothing else works, wipe and retry:**
   ```bash
   just wipe
   source "${XDG_CACHE_HOME:-$HOME/.cache}/sugarkube/wipe-env.sh"
   export SUGARKUBE_TOKEN_DEV="<token-from-bootstrap-node>"
   export SUGARKUBE_SERVERS=3
   just up dev
   ```

---

### Scenario 5: Time Synchronization Issues

**Symptom:**
k3s fails to start or etcd cluster formation fails with errors about time synchronization. You may see "clock drift" warnings or the time sync prerequisite check fails.

**Which logs to inspect:**

1. **Up logs showing time sync checks:**
   ```bash
   cat logs/up/<log-file> | grep -i "time\|chrony\|ntp"
   ```

2. **System time synchronization status:**
   ```bash
   timedatectl status
   chronyc tracking  # If using chrony
   systemctl status systemd-timesyncd  # If using timesyncd
   ```

3. **k3s logs for clock-related errors:**
   ```bash
   sudo journalctl -u k3s | grep -i "clock\|time\|sync" | tail -20
   ```

**Example log patterns to look for:**

**Time sync prerequisite check failure:**
```
[sugarkube] ERROR: Time synchronization failed. Clock offset is 1500ms (threshold: 500ms)
[sugarkube] Set SUGARKUBE_FIX_TIME=1 to force clock sync, or SUGARKUBE_STRICT_TIME=0 to ignore
```

**etcd rejecting join due to clock drift:**
```
etcdserver: request timed out
the clock difference against peer is too high
```

**Chrony reporting large offset:**
```
System time: 1.234 seconds slow of NTP time
```

**Next steps:**

1. **Check current time synchronization state:**
   ```bash
   # General status
   timedatectl status
   # Look for "System clock synchronized: yes"
   
   # If using chrony
   chronyc tracking
   # Check "System time" offset (should be under 0.5 seconds)
   
   # If using systemd-timesyncd
   timedatectl show-timesync --all
   ```

2. **Force immediate time synchronization:**
   ```bash
   # If using chrony (requires SUGARKUBE_FIX_TIME=1 in sugarkube scripts)
   sudo chronyc -a makestep
   
   # If using systemd-timesyncd
   sudo systemctl restart systemd-timesyncd
   timedatectl set-ntp true
   ```

3. **Allow sugarkube to fix time automatically:**
   ```bash
   export SUGARKUBE_FIX_TIME=1
   just up dev
   ```
   This permits the setup script to run `chronyc -a makestep` if the offset exceeds 500ms.

4. **Temporarily disable strict time checking (NOT recommended for production):**
   ```bash
   export SUGARKUBE_STRICT_TIME=0
   just up dev
   ```
   This allows the setup to proceed with a warning instead of failing.

5. **Configure time sync properly for long-term:**
   ```bash
   # Ensure time sync service is enabled
   sudo systemctl enable --now chronyd
   # or
   sudo systemctl enable --now systemd-timesyncd
   
   # Add reliable NTP servers to chrony config
   sudo nano /etc/chrony/chrony.conf
   # Add lines like:
   # server time.cloudflare.com iburst
   # server time.google.com iburst
   
   # Restart chrony
   sudo systemctl restart chronyd
   ```

6. **Verify time sync before retrying cluster join:**
   ```bash
   # Wait for time to synchronize (may take 30-60 seconds)
   watch -n 1 'timedatectl status | grep synchronized'
   
   # Once synchronized, retry
   just up dev
   ```

---

### Scenario 6: Firewall or Network Policy Blocking Cluster Traffic

**Symptom:**
Nodes can ping each other and resolve `.local` hostnames, but cluster formation fails. Discovery may succeed, but k3s service timeouts occur with connection refused or timeout errors.

**Which logs to inspect:**

1. **Up logs showing discovery vs installation phase:**
   ```bash
   cat logs/up/<log-file> | grep -E "event=discover|event=install"
   ```

2. **Network connectivity tests:**
   ```bash
   # Test k3s API port
   nc -zv sugarkube0.local 6443
   
   # For HA clusters, test etcd ports
   nc -zv sugarkube0.local 2379
   nc -zv sugarkube0.local 2380
   ```

3. **Firewall rules:**
   ```bash
   sudo iptables -L -n | grep -E "6443|2379|2380|5353"
   sudo ip6tables -L -n | grep -E "6443|2379|2380|5353"
   ```

**Example log patterns to look for:**

**Discovery succeeds but install fails:**
```
event=discover event=simple_discovery_found_servers count=1
...
event=install msg="API never became ready" timeout_seconds=120
```
Discovery found a server but couldn't actually connect to it.

**Connection refused in k3s logs:**
```
dial tcp 192.168.1.100:6443: connect: connection refused
dial tcp 192.168.1.100:2379: connect: no route to host
```
Firewall or routing is blocking the connection.

**Next steps:**

1. **Verify ports are listening on the bootstrap node:**
   ```bash
   # On bootstrap node (sugarkube0)
   sudo ss -tlnp | grep -E ":(6443|2379|2380)"
   # Should show k3s listening on these ports
   ```

2. **Test connectivity from joining node:**
   ```bash
   # From joining node (sugarkube1)
   curl -k https://sugarkube0.local:6443/livez
   # Should return HTTP 200 or 401 (not connection refused)
   ```

3. **Check for Docker/Podman firewall interference:**
   ```bash
   # If you have Docker installed, it may conflict with k3s
   sudo systemctl status docker
   sudo systemctl status podman
   # Consider disabling: sudo systemctl disable --now docker
   ```

4. **Verify no iptables rules are blocking k3s:**
   ```bash
   # Check if any DROP rules exist for k3s ports
   sudo iptables -L -v -n | grep -E "6443|2379|2380"
   
   # If you find blocking rules, you may need to add ACCEPT rules
   # Example (adjust as needed):
   sudo iptables -I INPUT -p tcp --dport 6443 -j ACCEPT
   sudo iptables -I INPUT -p tcp --dport 2379 -j ACCEPT
   sudo iptables -I INPUT -p tcp --dport 2380 -j ACCEPT
   ```

5. **Check UFW or firewalld if installed:**
   ```bash
   # UFW
   sudo ufw status
   sudo ufw allow 6443/tcp
   sudo ufw allow 2379:2380/tcp
   
   # firewalld
   sudo firewall-cmd --list-all
   sudo firewall-cmd --permanent --add-port=6443/tcp
   sudo firewall-cmd --permanent --add-port=2379-2380/tcp
   sudo firewall-cmd --reload
   ```

6. **Verify multicast is allowed for mDNS (UDP 5353):**
   ```bash
   # Allow mDNS multicast
   sudo iptables -I INPUT -p udp --dport 5353 -j ACCEPT
   sudo iptables -I OUTPUT -p udp --dport 5353 -j ACCEPT
   ```

7. **Test with firewall temporarily disabled (diagnostic only):**
   ```bash
   # Save current rules
   sudo iptables-save > /tmp/iptables-backup.rules
   
   # Flush all rules (CAUTION: SSH may break)
   sudo iptables -F
   sudo iptables -X
   sudo iptables -P INPUT ACCEPT
   sudo iptables -P FORWARD ACCEPT
   sudo iptables -P OUTPUT ACCEPT
   
   # Try cluster join again
   just up dev
   
   # Restore rules afterward
   sudo iptables-restore < /tmp/iptables-backup.rules
   ```

---

## Log Interpretation Quick Reference

### Structured Log Fields

Sugarkube logs use key=value pairs for structured information:

| Field | Meaning | Example Values |
|-------|---------|----------------|
| `ts=` | Timestamp in ISO 8601 format | `2025-11-10T06:29:15-08:00` |
| `level=` | Log level | `info`, `warn`, `error` |
| `event=` | Event type or phase | `discover`, `install`, `mdns_publish` |
| `outcome=` | Result of operation | `ok`, `timeout`, `fail` |
| `ms_elapsed=` | Duration in milliseconds | `125`, `20088` (values <200 are normal) |
| `severity=` | Severity indicator | `info`, `warn`, `error` |
| `token_present=` | Whether token was provided | `0` (no), `1` (yes) |
| `count=` | Number of items found | `0`, `1`, `3` |

### Common Event Types

| Event | Phase | What It Means |
|-------|-------|---------------|
| `event=discover` | Discovery | Node is searching for existing servers |
| `event=token_resolution` | Pre-flight | Checking if token is available |
| `event=mdns_absence_gate` | Pre-discovery | Waiting for old advertisements to clear |
| `event=mdns_publish` | Bootstrap | Publishing k3s API service via mDNS |
| `event=mdns_selfcheck` | Bootstrap | Verifying own service is discoverable |
| `event=simple_discovery_found_servers` | Discovery | Servers found via mDNS browsing |
| `event=install` | Installation | k3s installation and start |
| `event=wait` | Post-install | Waiting for API to become ready |

### Timing Expectations

| Operation | Normal Duration | Investigate If Exceeds |
|-----------|----------------|------------------------|
| mDNS discovery | 50-200ms | 1000ms (1 second) |
| Avahi absence gate | 2-5 seconds | 20 seconds |
| k3s installation | 30-60 seconds | 120 seconds |
| API readiness | 20-40 seconds | 120 seconds |
| etcd member join | 10-20 seconds | 60 seconds |

### Redacted Patterns

When reviewing sanitized logs, remember these patterns indicate redacted data:

- `[REDACTED_IP]` — External IP address was removed
- `[REDACTED_SECRET]` — Token, password, or secret was removed
- MAC addresses are fully redacted
- Private IPs (10.x, 192.168.x, etc.) are preserved for debugging

---

## Advanced Debugging

### Enable Full Debug Output

For maximum verbosity during troubleshooting:

```bash
export SUGARKUBE_DEBUG=1
export SUGARKUBE_MDNS_WIRE_PROOF=1
export SUGARKUBE_MDNS_DBUS=1
export SAVE_DEBUG_LOGS=1
just up dev 2>&1 | tee /tmp/full-debug.log
```

This enables:
- Detailed Python-level debug messages
- Wire-level TCP connection proofs
- D-Bus communication diagnostics
- Saved timestamped log in `logs/up/`

### Capture mDNS Wire-Level Traffic

To see actual multicast packets on the network:

```bash
# Capture mDNS traffic for 30 seconds
sudo tcpdump -i eth0 -vv -n udp port 5353 -w /tmp/mdns-capture.pcap
# Press Ctrl+C after seeing some traffic

# View captured packets
sudo tcpdump -r /tmp/mdns-capture.pcap -vv -n
```

Look for:
- Query packets going out (asking for `_k3s-sugar-dev._tcp`)
- Response packets coming in (from other nodes' IP addresses)
- Consistency in source IPs (should match your cluster nodes)

### Compare Logs Across Nodes

When troubleshooting multi-node issues, compare logs side-by-side:

```bash
# Collect logs from all nodes
scp sugarkube0:sugarkube/logs/up/20*dev.log /tmp/node0.log
scp sugarkube1:sugarkube/logs/up/20*dev.log /tmp/node1.log
scp sugarkube2:sugarkube/logs/up/20*dev.log /tmp/node2.log

# Compare discovery results
grep "simple_discovery_found_servers" /tmp/node*.log
# Should show consistent counts across nodes

# Compare timing
grep "ms_elapsed" /tmp/node*.log | sort
# Identify if one node is significantly slower
```

### Collect Full Support Bundle

For comprehensive diagnostics to share with the community:

```bash
# Run the support bundle script
scripts/collect_support_bundle.py --output /tmp/sugarkube-bundle.tar.gz

# The bundle includes:
# - System information (OS, kernel, hardware)
# - Network configuration (interfaces, routes, DNS)
# - k3s status and logs
# - Avahi configuration and service files
# - Recent up logs from logs/up/
# - Node verifier output
```

---

## Getting Help

If you've tried the troubleshooting steps above and still can't resolve your issue:

1. **Collect diagnostic information:**
   - Save debug logs: `SAVE_DEBUG_LOGS=1 just up dev`
   - Run node verifier: `scripts/pi_node_verifier.sh --json`
   - Capture support bundle: `scripts/collect_support_bundle.py`

2. **Search existing documentation:**
   - [mDNS Troubleshooting Guide](mdns_troubleshooting.md) — Detailed mDNS debugging
   - [Runbook](runbook.md) — Operational procedures and recovery
   - [Outage Catalog](outage_catalog.md) — Known issues and resolutions

3. **Check outage logs:**
   - Browse `outages/*.json` for similar issues
   - Look for `longForm` references to detailed incident reports

4. **File an issue on GitHub:**
   - Include your debug logs (sanitized logs are safe to share)
   - Describe your environment (Pi model, OS version, network setup)
   - List the steps to reproduce the issue
   - Share the output of `scripts/pi_node_verifier.sh --full`

---

## Related Documentation

- [Raspberry Pi Cluster Setup (Quick Start)](raspi_cluster_setup.md) — Initial cluster bring-up
- [Raspberry Pi Cluster Operations](raspi_cluster_operations.md) — Day-two operations
- [mDNS Troubleshooting Guide](mdns_troubleshooting.md) — Deep dive into mDNS-specific issues
- [Runbook](runbook.md) — Operational procedures and SRE playbooks
- [Outage Catalog](outage_catalog.md) — Historical issues and resolutions
