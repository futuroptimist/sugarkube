# Sugarkube Debug Logs

This directory collects sanitized `just up` logs when `SAVE_DEBUG_LOGS=1` is exported during a bootstrap run. Files are named with the UTC timestamp, the checked-out commit hash, the hostname, and the environment to make it easy to pair logs from multiple nodes. Secrets and external IP addresses are redacted automatically before they are written here.

## Handling journald rate limits locally

Systemd's journal may drop frequent Avahi or network diagnostics if its rate limits are hit. Developers who need more verbose local capture can adjust the runtime configuration without editing repository files by running:

```bash
sudo mkdir -p /etc/systemd/journald.conf.d
cat <<'EOF' | sudo tee /etc/systemd/journald.conf.d/sugarkube-debug.conf
[Journal]
RateLimitIntervalSec=30s
RateLimitBurst=2000
EOF
sudo systemctl restart systemd-journald
```

These overrides live on the workstation only; do not commit them to the image or this repository. Tune `RateLimitIntervalSec` and `RateLimitBurst` to match your hardware if you still encounter dropped entries.
