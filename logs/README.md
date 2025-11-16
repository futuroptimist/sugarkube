# Sugarkube Debug Logs

This directory stores sanitized diagnostics that are safe to commit. The `debug-mdns.sh` helper
captures mDNS, Avahi, and network state while redacting IP/MAC addresses and filtering outputs to an
allowlist of hostnames.

## Running the sanitized mDNS collector

1. Adjust the hostname allowlist if needed:
   ```bash
   export MDNS_ALLOWED_HOSTS="sugarkube0.local sugarkube1.local other.local"
   ```
   If unset, the script defaults to `sugarkube0.local`, `sugarkube1.local`, and `sugarkube2.local`.
2. Generate a sanitized log from the repository root:
   ```bash
   cd logs
   ./debug-mdns.sh | tee "debug-mdns_$(date -u +%Y-%m-%dT%H:%M:%SZ).log.sanitized"
   ```
3. Commit or share the `.sanitized` file—raw IPs, MACs, and disallowed hostnames are removed.

## Handling `just up` debug logs

When `SAVE_DEBUG_LOGS=1` is exported during a bootstrap run, sanitized `just up` logs are written
here with UTC timestamps, the commit hash, hostname, and environment so multiple nodes can be paired
quickly. Secrets and external IP addresses are redacted automatically before they are stored.

## Handling journald rate limits locally

Systemd's journal may drop frequent Avahi or network diagnostics if its rate limits are hit.
Developers who need more verbose local capture can adjust the runtime configuration without editing
repository files by running:

```bash
sudo mkdir -p /etc/systemd/journald.conf.d
cat <<'JOURNAL' | sudo tee /etc/systemd/journald.conf.d/sugarkube-debug.conf
[Journal]
RateLimitIntervalSec=30s
RateLimitBurst=2000
JOURNAL
sudo systemctl restart systemd-journald
```

These overrides live on the workstation only; do not commit them to the image or this repository.
Tune `RateLimitIntervalSec` and `RateLimitBurst` to match your hardware if you still encounter
dropped entries.
