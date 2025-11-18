# Sugarkube Debug Logs

This directory collects sanitized `just up` logs when `SAVE_DEBUG_LOGS=1` is exported during a
bootstrap run. Files are named with the UTC timestamp, the checked-out commit hash, the hostname,
and the environment to make it easy to pair logs from multiple nodes. Secrets and external IP
addresses are redacted automatically before they are written here.

## Sanitized mDNS debug output

Use `logs/debug-mdns.sh` to gather mDNS and k3s discovery diagnostics that can be committed without
leaking WAN IPs or local network details.

### Allowlisting hostnames

By default the script keeps only `_k3s-sugar-dev._tcp` records plus hostnames in the allowlist:
`sugarkube0.local`, `sugarkube1.local`, and `sugarkube2.local`. Override the allowlist and collect
sanitized output in one command:

```bash
MDNS_ALLOWED_HOSTS="sugarkube0.local sugarkube1.local sugarkube2.local" ./logs/debug-mdns.sh | tee \
  logs/up/debug-mdns_$(date -u +"%Y-%m-%dT%H:%M:%SZ").log.sanitized
```

The resolved IP addresses are redacted in the output regardless of the allowlist.

The script summarizes tcpdump, ping, and curl checks instead of printing packet contents.

## Handling journald rate limits locally

Systemd's journal may drop frequent Avahi or network diagnostics if its rate limits are hit.
Developers who need more verbose local capture can adjust the runtime configuration without editing
repository files by running:

```bash
sudo mkdir -p /etc/systemd/journald.conf.d
cat <<'CONF' | sudo tee /etc/systemd/journald.conf.d/sugarkube-debug.conf
[Journal]
RateLimitIntervalSec=30s
RateLimitBurst=2000
CONF
sudo systemctl restart systemd-journald
```

These overrides live on the workstation only; do not commit them to the image or this repository.
Tune `RateLimitIntervalSec` and `RateLimitBurst` to match your hardware if you still encounter
dropped entries.
