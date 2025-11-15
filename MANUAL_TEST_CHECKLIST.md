# Manual Testing Checklist for Raspberry Pi 5 Cluster

**Date**: 2025-11-15  
**Fix Applied**: Phase 3/4 compatibility - enabled service advertisement by default  
**PR**: Setup Raspberry Pi 5 cluster  
**Related Outage**: `outages/2025-11-15-phase3-phase4-incompatibility.md`

---

## Prerequisites

- [ ] 3x Raspberry Pi 5 boards (sugarkube0, sugarkube1, sugarkube2)
- [ ] All connected to same switch/subnet
- [ ] Each has unique hostname configured
- [ ] Fresh Raspberry Pi OS installation (or wiped with `just wipe`)
- [ ] Pull latest code from branch: `copilot/setup-raspberry-pi-5-cluster`

---

## Test Scenario 1: 2-Node HA Cluster Formation

### Step 1: Bootstrap sugarkube0

On sugarkube0:
```bash
# First run (memory cgroup setup + reboot)
export SUGARKUBE_SERVERS=3
export SAVE_DEBUG_LOGS=1
just up dev

# Wait for automatic reboot (~1 minute)

# After reboot, SSH back in and run second time (k3s bootstrap)
export SUGARKUBE_SERVERS=3
export SAVE_DEBUG_LOGS=1
just up dev
```

**Expected behavior:**
- First run: Edits `/boot/cmdline.txt`, reboots automatically
- Second run: 
  - Installs k3s as first HA server with `--cluster-init`
  - Publishes mDNS service `_k3s-sugar-dev._tcp` on port 6443
  - Logs show: `event=publish_bootstrap_service role=bootstrap`
  - NO log line: `event=service_advertisement_skipped` (this was the bug!)
  - Completes in ~2-3 minutes

**Verification:**
```bash
# On sugarkube0
sudo systemctl status k3s
sudo k3s kubectl get nodes
avahi-browse --all --resolve --terminate | grep -A2 '_https._tcp'
# Should see: port 6443, TXT: k3s=1, cluster=sugar, env=dev, role=server

# Capture token for other nodes
sudo cat /var/lib/rancher/k3s/server/node-token
# Save this K10... token for Step 2
```

**Success criteria:**
- [ ] k3s service running and healthy
- [ ] Node shows as Ready
- [ ] mDNS service visible via `avahi-browse`
- [ ] Token captured

### Step 2: Join sugarkube1

On sugarkube1:
```bash
# First run (memory cgroup setup + reboot)
export SUGARKUBE_SERVERS=3
export SAVE_DEBUG_LOGS=1
just up dev

# Wait for automatic reboot

# After reboot, export token and run second time
export SUGARKUBE_SERVERS=3
export SUGARKUBE_TOKEN_DEV="K10..." # paste token from sugarkube0
export SAVE_DEBUG_LOGS=1
just up dev
```

**Expected behavior:**
- First run: Memory cgroup setup, reboot
- Second run:
  - Uses simple discovery (Phase 3) to find sugarkube0
  - Logs show: `event=simple_discovery_start`
  - Logs show: `event=simple_discovery_found server=sugarkube0.local`
  - Logs show: `event=simple_discovery_api_ok`
  - Joins as second HA server
  - Completes in ~1-2 minutes

**Verification:**
```bash
# On sugarkube1
sudo systemctl status k3s
sudo k3s kubectl get nodes
# Should see both sugarkube0 and sugarkube1

# On either node
sudo k3s kubectl get nodes -o wide
# Both nodes should show Ready

# Check etcd members
sudo k3s etcd-snapshot save --name test
# Should show 2 members
```

**Success criteria:**
- [ ] sugarkube1 discovered sugarkube0 automatically (no hardcoded hostname needed)
- [ ] k3s service running on sugarkube1
- [ ] Both nodes show as Ready
- [ ] etcd has 2 members
- [ ] No errors in logs about missing services or discovery failures

---

## Test Scenario 2: Complete 3-Node HA Cluster

### Step 3: Join sugarkube2

Repeat Step 2 on sugarkube2 (same process as sugarkube1).

**Expected behavior:**
- Discovers either sugarkube0 or sugarkube1 via mDNS
- Joins as third HA server
- Forms complete etcd quorum (3 members)

**Verification:**
```bash
# On any node
sudo k3s kubectl get nodes
# Should see all 3 nodes Ready

sudo k3s etcd-snapshot save --name test
# Should show 3 members

# Deploy test workload
sudo k3s kubectl run test-nginx --image=nginx:alpine
sudo k3s kubectl get pods
# Pod should be scheduled and running
```

**Success criteria:**
- [ ] All 3 nodes show Ready
- [ ] etcd has 3 members (healthy quorum)
- [ ] Test workload deploys successfully
- [ ] All nodes can schedule pods

---

## Log Collection

After each run, logs are saved to `logs/up/` with format:
```
logs/up/YYYYMMDDTHHMMSSZ_<hash>_<hostname>_just-up-<env>.log
```

**Key log patterns to look for:**

### ✅ Success patterns:
```
event=simple_discovery_found server=sugarkube0.local
event=simple_discovery_api_ok
event=publish_bootstrap_service role=bootstrap
phase=install_join server=sugarkube0.local
```

### ❌ Failure patterns (shouldn't appear with fix):
```
event=service_advertisement_skipped reason=SUGARKUBE_SKIP_SERVICE_ADVERTISEMENT=1
event=simple_discovery_no_servers token_present=1
event=simple_discovery_fail
```

---

## Troubleshooting

### If discovery still fails:

1. **Check Avahi is running:**
   ```bash
   sudo systemctl status avahi-daemon
   ```

2. **Verify multicast is working:**
   ```bash
   avahi-browse --all --resolve --terminate
   # Should see services from other nodes
   ```

3. **Check firewall:**
   ```bash
   # UDP 5353 must be open for mDNS
   sudo iptables -L -n | grep 5353
   ```

4. **Manual service check:**
   ```bash
   # On bootstrap node (sugarkube0)
   ls -la /etc/avahi/services/
   # Should see k3s-sugar-dev.service
   
   cat /etc/avahi/services/k3s-sugar-dev.service
   # Should contain proper XML service definition
   ```

5. **Try explicit discovery:**
   ```bash
   # On joining node
   avahi-resolve -n sugarkube0.local
   # Should return IP address
   
   curl -k https://sugarkube0.local:6443/
   # Should return 401 (unauthorized but alive)
   ```

---

## Rollback Plan

If testing reveals issues:

1. **Disable the fix temporarily:**
   ```bash
   # On bootstrap node
   export SUGARKUBE_SKIP_SERVICE_ADVERTISEMENT=1
   export SUGARKUBE_SIMPLE_DISCOVERY=0  # Use legacy discovery
   just up dev
   ```

2. **Report findings:**
   - Capture all log files from `logs/up/`
   - Run diagnostics: `sudo k3s check-config`
   - Document specific failure mode

3. **Clean slate:**
   ```bash
   just wipe
   sudo reboot
   ```

---

## Success Confirmation

Final checklist after completing all tests:

- [ ] 3-node cluster formed successfully
- [ ] All nodes discovered each other automatically (no manual intervention)
- [ ] No Phase 3/4 incompatibility errors in logs
- [ ] etcd quorum is healthy (3 members)
- [ ] Test workload deploys and runs
- [ ] Nodes can be rebooted and rejoin cluster automatically

---

## Report Results

After testing, report results in PR with:
1. Test scenario outcomes (success/failure for each step)
2. Attached log files (sanitized via SAVE_DEBUG_LOGS=1)
3. Any unexpected behavior or issues discovered
4. Performance observations (discovery time, join time)
5. Screenshots of `k3s kubectl get nodes` showing final cluster state
