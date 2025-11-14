# Sugarkube Debug Logs

This directory collects sanitized `just up` logs when `SAVE_DEBUG_LOGS=1` is exported during a bootstrap run. Files are named with the UTC timestamp, the checked-out commit hash, the hostname, and the environment to make it easy to pair logs from multiple nodes. Secrets and external IP addresses are redacted automatically before they are written here.

## journald headroom for local debugging

`just up` relies on systemd-journald for transient service logs. Developers who
want longer retention while iterating locally can relax journald's rate limits
by dropping an override on their workstation or test Pi:

```
sudo mkdir -p /etc/systemd/journald.conf.d
sudo tee /etc/systemd/journald.conf.d/10-sugarkube-debug.conf <<'EOF'
[Journal]
RateLimitIntervalSec=30s
RateLimitBurst=10000
EOF
sudo systemctl restart systemd-journald
```

The `RateLimitIntervalSec` and `RateLimitBurst` knobs control how aggressively
systemd throttles chatty services. Adjust them to match your local storage and
debugging needs, but keep the overrides on your machine only—do not commit them
to Sugarkube's source tree or baked images.
