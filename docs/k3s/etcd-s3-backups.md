# k3s etcd snapshots with S3 offload

k3s bundles an embedded etcd cluster that can take scheduled snapshots of the control-plane state.
By default snapshots remain on each server's filesystem, but k3s can also upload them to an S3
bucket for durable off-cluster backups.

## Server configuration example

Place the following configuration on each server under `/etc/rancher/k3s/config.yaml`. It disables
the bundled `servicelb` (kube-vip already provides a load balancer), enables twice-daily etcd
snapshots, retains 28 local snapshots per server (about 14 days at two snapshots per day),
and pushes copies to an S3 bucket. This is a configuration example, not measured backup coverage.
Provide credentials through a separately reviewed protected configuration; do not publish values.
Verify remote retention and bucket lifecycle independently for the exact installed version;
local retention does not establish the remote recovery window. See the
[K3s snapshot reference](https://docs.k3s.io/cli/etcd-snapshot).

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

## Restore qualification and procedure

Use the canonical [snapshot restore procedure](../runbook.md#restoring-etcd-from-snapshots)
and [qualification checklist](../runbook.md#offline-restore-qualification-record).
That procedure requires a clean environment, exactly one isolated selected seed, preserved
peer data, sequential rejoin, and independent acceptance gates. Ready nodes alone do not prove
restored data. Existing-database recovery is distinct from scheduled-snapshot restoration.

Do not execute a restore from this configuration guide. Repository checks and synthetic fixtures
cannot qualify a live restore or close [#2919](https://github.com/futuroptimist/sugarkube/issues/2919).
