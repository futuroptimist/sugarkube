# k3s etcd snapshots and S3 backups

## Overview

k3s bundles an embedded etcd cluster that automatically snapshots the datastore to the
`/var/lib/rancher/k3s/server/db/snapshots` directory. By default, snapshots are retained locally;
enabling the built-in S3 integration mirrors each snapshot to an object store so the cluster can be
rebuilt even if the control-plane nodes are lost.

## Example server configuration

Add the following options to `/etc/rancher/k3s/config.yaml` on each server node. The schedule keeps
local copies and uploads every snapshot to an S3 bucket. Nodes can either rely on IAM instance
profiles or populate the commented environment variables in `/etc/rancher/k3s/k3s.env`.

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

## Ensure snapshot directory exists on first server

Create a small systemd unit on the first control-plane node so the snapshot directory exists before
k3s writes backups.

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

Stop k3s on all control-plane nodes, download the desired snapshot (from local disk or S3), then
reset the cluster using that snapshot on a single node:

```bash
sudo k3s server --cluster-init --cluster-reset --cluster-reset-restore-path \
  /var/lib/rancher/k3s/server/db/snapshots/<snapshot>
```

Remove the reset flags from the configuration file before restarting k3s elsewhere so the cluster
rejoins normally.
