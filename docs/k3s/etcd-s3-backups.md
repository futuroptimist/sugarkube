# k3s etcd snapshots and S3 offload

k3s embeds etcd and can manage scheduled snapshots without any external controller. Snapshots can be
stored locally on the server and, when enabled, uploaded to an S3-compatible object store for
long-term retention. The configuration below keeps local copies for fast recovery while pushing
archives to S3 every 12 hours.

## Example server configuration

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

## Ensure snapshot directory on boot

Add a simple oneshot unit on the first server node so that the snapshot directory exists before the
scheduler runs:

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

Enable the unit and restart the node if needed:

```bash
sudo cp ensure-k3s-snapshots.service /etc/systemd/system/
sudo systemctl enable --now ensure-k3s-snapshots.service
```

## Restore quickstart

To restore the cluster, stop k3s on all nodes, copy the desired snapshot to the first control-plane,
and run k3s in reset mode pointing at the snapshot file:

```bash
sudo k3s server --cluster-init --cluster-reset \
  --cluster-reset-restore-path /var/lib/rancher/k3s/server/db/snapshots/<snapshot>
```

After the reset completes, remove the reset flags from `/etc/rancher/k3s/config.yaml`, restart k3s on
the remaining nodes, and confirm the etcd members rejoin.
