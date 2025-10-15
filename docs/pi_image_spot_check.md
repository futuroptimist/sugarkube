# ✅ Raspberry Pi Image Verification — General Template

This document serves as a standardized checklist for validating a freshly flashed Raspberry Pi image prior to cloning from SD → SSD and proceeding with Kubernetes (k3s) setup.

---

## 1. System Baseline
Verify the image boots and reports the expected OS and kernel:
```
uname -a
cat /etc/os-release
```
Confirm:
- OS: Raspbian or Raspberry Pi OS Bookworm (12)
- Kernel: 6.12.x or later
- Architecture: aarch64
- Hostname matches your node label (e.g., `sugarkube0`)

Check timezone and locale:
```
timedatectl
locale
```
✅ Ensure NTP = active, time zone matches your region, and locale is consistent.

---

## 2. Storage and Partitioning
```
df -h
lsblk -o NAME,FSTYPE,SIZE,MOUNTPOINT
sudo blkid
```
Record:
- Root partition (`/`) → `/dev/mmcblk0p2`  
- Boot partition → `/dev/mmcblk0p1`
- Verify expected free space and correct mountpoints.
- Note UUIDs for `/boot/firmware` and `/`.

Example:
| Device | Label | Type | Size | Mount | UUID |
|--------|--------|------|------|--------|------|
| /dev/mmcblk0p1 | bootfs | vfat | 512 M | /boot/firmware | XXXX-XXXX |
| /dev/mmcblk0p2 | rootfs | ext4 | 64 G + | / | XXXXXXXX-XXXX |

---

## 3. Networking
Check LAN and Internet reachability:
```
ping -c3 <router_ip>
ping -c3 google.com
```
💡 *Your local IP range may differ (e.g., 192.168.x.x, 10.x.x.x, 172.16.x.x); adjust accordingly.*

Expect 0 % packet loss and < 10 ms latency on LAN.

---

## 4. Services and Boot Logs
```
sudo systemctl list-units --type=service | grep -E 'flywheel|k3s|cloudflared|containerd'
sudo journalctl -b -p 3 --no-pager
```
Confirm:
- No unexpected services auto-started.
- Boot log errors limited to benign messages (Bluetooth plugin init, etc.).

---

## 5. System Health Snapshot
```
vcgencmd measure_temp
free -h
sudo dmesg | tail -20
```
Guidelines:
- Temp < 60 °C at idle.
- > 7 Gi RAM available (on Pi 5 8 GB model).
- No kernel errors or I/O warnings.

---

## 6. Repository Sync (if applicable)
Ensure expected repositories were cloned automatically or are present:
- `sugarkube`
- `dspace`
- `token.place`
(others optional depending on image profile)

---

## 7. Verification Summary
| Check | Status | Notes |
|--------|---------|-------|
| OS / Kernel | ✅ | Matches expected Bookworm build |
| Hostname / Hosts | ✅ | Consistent |
| Disk Health | ✅ | Root mounted on SD, ample space |
| Network | ✅ | LAN and WAN reachable |
| Temp / Memory | ✅ | Within normal range |
| Boot Logs | ✅ | No critical errors |

---

## 8. Next Steps (Post-Verification)
1. **Shutdown**  
   ```
   sudo poweroff
   ```
2. **Attach SSD** via USB 3.0.
3. **Boot and confirm SSD visibility:**  
   ```
   lsblk
   ```
4. **Clone SD → SSD:**
   > **Note:** Raspberry Pi OS Bookworm mounts the boot partition at `/boot/firmware`.
   > Before running `just clone-ssd`, bind-mount it so the helper can find it:
   > ```
   > sudo mkdir -p /boot
   > sudo mount --bind /boot/firmware /boot
   > ```
   ```
   sudo rpi-clone sda -f
   ```
   *(or run `just clone-ssd` if defined in your Justfile)*
5. **Update UUIDs:**  
   - `/boot/firmware/cmdline.txt`  
   - `/etc/fstab`
6. **Reboot → Verify:**  
   ```
   df -h | grep '^/dev/sda'
   ```
7. Proceed to `just k3s-init` or your cluster bootstrap command.

---

**Result:**  
✅ All baseline checks passed. The image is stable and ready for SSD cloning and k3s setup.
