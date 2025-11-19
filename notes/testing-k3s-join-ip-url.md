# Testing Guide: k3s Join with IP-based Server URLs

## What Changed

Modified `scripts/k3s-discover.sh` to use IP addresses instead of mDNS hostnames in the k3s server URL when joining nodes. This fixes an issue where k3s.service would fail to start because systemd services cannot reliably resolve `.local` hostnames via mDNS.

### Functions Modified
1. `install_server_join()` - Used when joining additional server nodes to form HA cluster
2. `install_agent()` - Used when joining worker/agent nodes

### Key Changes
- When `ip_hint` is available (populated from `MDNS_SELECTED_IP`), use it in:
  - `K3S_URL` environment variable
  - `--server` command-line flag
- Hostname is preserved in `--tls-san` flags for proper TLS certificate verification
- Falls back to hostname if IP is not available (backward compatible)
- Added logging to show which type is being used

## Expected Behavior

### Before Fix
```
K3S_URL=https://sugarkube0.local:6443
--server "https://sugarkube0.local:6443"
→ k3s.service fails to start (cannot resolve hostname)
```

### After Fix (Normal Case - IP Available)
```
K3S_URL=https://192.168.86.41:6443
--server "https://192.168.86.41:6443"
--tls-san "sugarkube0.local"  (for cert verification)
→ k3s.service starts successfully
```

### After Fix (Fallback - IP Not Available)
```
K3S_URL=https://sugarkube0.local:6443
--server "https://sugarkube0.local:6443"
→ Same as before (backward compatible)
```

## Manual Testing on Real Hardware

### Prerequisites
- Two Raspberry Pi devices on the same network
- Both running Raspberry Pi OS with sugarkube repository cloned
- Both have mDNS/Avahi configured

### Test Steps

#### 1. Bootstrap First Node (sugarkube0)
```bash
cd ~/sugarkube
just wipe
export SUGARKUBE_SERVERS=3
export SAVE_DEBUG_LOGS=1
just up dev
```

**Expected:**
- Node bootstraps successfully
- k3s.service is running: `systemctl status k3s`
- mDNS service published: `avahi-browse -rt _k3s-sugar-dev._tcp`

**Capture token:**
```bash
sudo cat /var/lib/rancher/k3s/server/node-token
```

#### 2. Join Second Node (sugarkube1)
```bash
cd ~/sugarkube
just wipe
export SUGARKUBE_SERVERS=3
export SAVE_DEBUG_LOGS=1
export SUGARKUBE_TOKEN_DEV="<token-from-sugarkube0>"
just up dev
```

**Expected:**
- Discovery succeeds (should see in logs):
  ```
  event=discover event=simple_discovery_success server=sugarkube0.local
  event=discover event=mdns_select ... ip="192.168.86.41"
  ```

- **NEW**: Log shows IP-based URL being used:
  ```
  event=install_join server_url_type=ip server_url="192.168.86.41" hostname="sugarkube0.local"
  ```

- k3s installation completes
- **CRITICAL**: k3s.service starts successfully: `systemctl status k3s`
- Node joins cluster: `kubectl get nodes` (should show both nodes)

#### 3. Verify Cluster Formation
On either node:
```bash
sudo kubectl get nodes -o wide
```

**Expected output:**
```
NAME          STATUS   ROLES                       AGE   VERSION        INTERNAL-IP
sugarkube0    Ready    control-plane,etcd,master   5m    v1.33.5+k3s1   192.168.86.41
sugarkube1    Ready    control-plane,etcd,master   2m    v1.33.5+k3s1   192.168.86.42
```

#### 4. Check Logs
View the saved debug log on sugarkube1:
```bash
cd ~/sugarkube
cat logs/up/$(ls -t logs/up/ | head -1)
```

**Look for:**
1. Discovery success: `event=simple_discovery_success`
2. IP selection: `event=mdns_select ... ip="192.168.86.41"`
3. **NEW**: URL type logging: `event=install_join server_url_type=ip server_url="192.168.86.41"`
4. No errors after k3s installation starts

### Troubleshooting

#### If k3s.service still fails
Check the service logs:
```bash
sudo journalctl -xeu k3s.service
```

Look for DNS resolution errors or connection failures.

#### If logs show hostname instead of IP
Check if IP was discovered:
```bash
grep "event=mdns_select" logs/up/$(ls -t logs/up/ | head -1)
```

Should show `ip="<some-ip>"`. If not, mDNS discovery didn't provide the IP.

#### Verify systemd service environment
Check what K3S_URL was set:
```bash
cat /etc/systemd/system/k3s.service.env | grep K3S_URL
```

Should show: `K3S_URL=https://192.168.86.41:6443` (IP, not hostname)

## Automated Testing

While manual testing is required on real hardware, the changes can be unit tested by:

1. Mocking the `ip_hint` variable
2. Capturing the environment variables passed to `run_k3s_install`
3. Verifying `K3S_URL` contains the IP when `ip_hint` is set
4. Verifying `--server` flag contains the IP when `ip_hint` is set
5. Verifying `--tls-san` still contains the original hostname

This would require extracting the logic into a testable function or using bash testing frameworks like BATS.

## Rollback Plan

If this change causes issues:
1. Revert the commit
2. Apply workaround: Manually edit `/etc/systemd/system/k3s.service.env` to replace hostname with IP
3. Restart k3s: `sudo systemctl restart k3s`
