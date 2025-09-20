# Pi Boot & Cluster Troubleshooting Matrix

This quick-reference collects the symptoms we see most often after flashing a
sugarkube image. Each row links LED behaviors, log locations, and recovery
steps so you can jump straight to the relevant command.

Keep the matrix close at hand by printing the [Pi carrier QR labels](./pi_carrier_qr_labels.md).
Stick the troubleshooting label on the carrier so operators can scan it and jump straight to this
guide the moment a boot hiccup appears.

> **Tip:** Run everything in a terminal with `watch -n 5` when waiting for
> services to converge. Watching the same command update in place makes it
> obvious when a subsystem recovers.

## Quick lookup table

| Symptom | LED pattern | Primary checks | Likely root cause | Recommended fix |
| --- | --- | --- | --- | --- |
| Power on but no video | Steady red, no green | `vcgencmd get_throttled`, reseat SD | Insufficient power or SD card not seated | Swap power supply, reinsert SD/SSD, confirm `lsblk` shows the boot media. |
| Stuck on rainbow splash | Green LED blinking in 4-4 pattern | Inspect `/boot/firmware/config.txt`, `dmesg` | GPU firmware mismatch or corrupt boot files | Reflash boot partition, copy `/boot/firmware` from fresh release, rerun verifier. |
| Boots but no network | Solid green after boot | `nmcli device status`, `journalctl -u systemd-networkd` | Missing Wi-Fi credentials or DHCP failure | Re-run `install_sugarkube_image.sh` with `--secrets`, verify router DHCP, check cable. |
| `cloud-init` never finishes | Green LED heartbeat, login prompt available | `sudo cloud-init status --long`, `journalctl -u cloud-init` | Secret injection or package download stalled | Clear with `sudo cloud-init clean`, fix network, rerun verifier. |
| k3s node stays `NotReady` | Normal LEDs | `sudo kubectl get nodes`, `journalctl -u k3s` | Container runtime not started or cgroup config drift | Reboot once, then inspect `/var/log/syslog` for `containerd`; run `sudo systemctl restart k3s`. |
| `projects-compose` fails | Normal LEDs | `sudo systemctl status projects-compose`, `docker compose logs` | Image pull failures or secrets missing | Run `sudo systemctl restart projects-compose`, verify `/opt/projects/.env`, re-run `pi_node_verifier.sh`. |
| token.place down | Normal LEDs | `curl -fkL https://token.place/healthz`, `sudo docker compose ps` | Compose service unhealthy or TLS misconfigured | Restart compose stack, check `docker compose logs token.place`, trust anchors under `/etc/ssl`. |
| dspace API unreachable | Normal LEDs | `curl -f http://127.0.0.1:8000/graphql`, `sudo docker compose ps` | Background migrations or Postgres init failed | Tail `docker compose logs dspace`, confirm `postgres` container ready, rerun migrations. |
| SSD clone stalls | Normal LEDs | `journalctl -u ssd-clone`, `sudo lsblk`, `iotop` | USB bridge resets or disk full | Re-seat USB/SATA cable, ensure target larger than source, use `--resume` when rerunning clone. |
| First boot report missing | Normal LEDs | `ls /boot`, `journalctl -u pi-node-verifier` | Verifier failed before report export | Manually run `sudo /usr/local/bin/pi_node_verifier.sh --report /boot/first-boot-report.txt`. |

## Command & log reference

- `vcgencmd get_throttled`: Returns a bit mask. `0x0` means power is good. Values like
  `0x50005` indicate undervoltage. Pair with `dmesg | grep voltage` to confirm.
- `sudo journalctl -u <service> --no-pager`: Replace `<service>` with `cloud-init`,
  `k3s`, or `projects-compose` to scroll recent failures.
- `sudo docker compose -f /opt/projects/docker-compose.yml logs --tail 50 <service>`:
  Target an individual container when the compose unit is active but unhealthy.
- `sudo kubectl get events --sort-by=.lastTimestamp`: Surface Kubernetes events
  such as image pulls that time out.
- `sudo pi-node-verifier --format markdown --output /tmp/verify.md`: On systems
  with the helper installed globally, regenerate reports without rebooting.

## When to escalate

If the table does not cover your scenario, collect the following bundle and
attach it to an issue or outage report:

```bash
sudo ./scripts/collect_support_bundle.sh --output ~/sugarkube/support-$(date +%Y%m%d).tar.gz
```

The archive gathers `journalctl`, compose logs, `kubectl get all -A`, and the
latest `/boot/first-boot-report.txt`, making it easier to spot regressions.
