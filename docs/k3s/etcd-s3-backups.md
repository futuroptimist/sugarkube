# k3s etcd snapshots with S3 offload

k3s bundles an embedded etcd cluster that can take scheduled snapshots of the control-plane state.
By default snapshots remain on the first server's filesystem, but k3s can also upload them to an S3
bucket for durable off-cluster backups.

## Server configuration example

Place the following configuration on each server under `/etc/rancher/k3s/config.yaml`. It disables
the bundled `servicelb` (kube-vip already provides a load balancer), enables twice-daily etcd
snapshots, keeps four weeks of history, and pushes copies to an S3 bucket. Provide credentials via
an IAM role attached to the node or by uncommenting the inline environment variables.

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

The first control-plane node should create the snapshot directory before k3s starts so that the
etcd manager can rotate backups without warnings. Add the following oneshot systemd unit and enable
it via `systemctl enable --now ensure-k3s-snapshot-dir.service`.

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

## Restore quickstart

To restore from a snapshot, copy it to the first server (or download it from S3), then start k3s in
reset mode pointing at the snapshot path. k3s reinitializes the datastore and halts so the
remaining servers can rejoin with their normal configuration.

```bash
sudo k3s server \
  --cluster-init \
  --cluster-reset \
  --cluster-reset-restore-path /var/lib/rancher/k3s/server/db/snapshots/<snapshot>
```

After the reset completes, remove the reset flags from the config file, restart k3s on all nodes,
and confirm `kubectl get nodes` reports each member as Ready.
