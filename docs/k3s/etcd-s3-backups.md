# k3s etcd snapshots and S3 offload

This guide documents how the sugarkube cluster schedules embedded etcd snapshots and exports them to
an object store. k3s can write recurring snapshots to local disk and, when configured, mirror each
archive to an S3-compatible bucket for off-cluster retention.

## Server configuration example

The following configuration keeps the embedded etcd snapshots enabled, disables the bundled
ServiceLB in favor of kube-vip, and pushes snapshots to S3 every 12 hours:

```yaml
# /etc/rancher/k3s/config.yaml
disable:
  - servicelb    # kube-vip provides L4
# etcd snapshots every 12h, keep 28, and push to S3
etcd-snapshot-schedule-cron: "0 */12 * * *"
etcd-snapshot-retention: 28
etcd-s3: true
etcd-s3-bucket: "sugarkube-k3s-backups"
etcd-s3-region: "us-east-1"
# either IAM on node or env file with creds:
# etcd-s3-access-key, etcd-s3-secret-key
```

Populate the access key and secret via node IAM credentials, an instance profile, or an environment
file referenced by `k3s.service`. The bucket must exist prior to enabling the snapshot sync.

## Ensure snapshot directory on boot

Create a oneshot unit on the first control-plane node so that the snapshot directory exists before
k3s writes to it:

```ini
[Unit]
Description=Ensure k3s snapshot dir
After=network-online.target

[Service]
Type=oneshot
ExecStart=/bin/mkdir -p /var/lib/rancher/k3s/server/db/snapshots

[Install]
WantedBy=multi-user.target
```

Enable the unit with `sudo systemctl enable --now ensure-k3s-snapshot-dir.service`.

## Restore quickstart

1. Stop k3s on all control-plane nodes (`sudo systemctl stop k3s`).
2. Copy the desired snapshot to `/var/lib/rancher/k3s/server/db/snapshots/` or download it from the
   configured bucket.
3. Start a single control-plane node in reset mode to replay the snapshot:

   ```bash
   sudo k3s server --cluster-init --cluster-reset --cluster-reset-restore-path /var/lib/rancher/k3s/server/db/snapshots/<snapshot>
   ```

4. Remove the reset flags from `/etc/rancher/k3s/config.yaml`, restart k3s normally, and allow the
   remaining control-plane nodes to rejoin the restored cluster.
