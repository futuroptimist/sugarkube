# Sugarkube Debug Logs

This directory collects sanitized diagnostics that are safe to store in the repository.

## `just up` capture

`just up` logs are saved automatically when `SAVE_DEBUG_LOGS=1` is exported during a
bootstrap run. Files are named with the UTC timestamp, the checked-out commit hash, the
hostname, and the environment to make it easy to pair logs from multiple nodes. Secrets
and external IP addresses are redacted automatically before they are written here.

## Sanitized mDNS diagnostics

Use `logs/debug-mdns.sh` to capture mDNS and k3s discovery details without leaking
addresses.

### Allowlist configuration

The script only includes mDNS records for the allowlisted hostnames plus the
`_k3s-sugar-dev._tcp` service. By default it keeps `sugarkube0.local`, `sugarkube1.local`,
and `sugarkube2.local`. Override the list at runtime:

```bash
MDNS_ALLOWED_HOSTS="sugarkube0.local lab-host.local" ./logs/debug-mdns.sh \
  > logs/debug-mdns_$(date -u +%FT%H-%M-%SZ).log.sanitized
```

### Running locally

1. Ensure the script is executable: `chmod +x logs/debug-mdns.sh`.
2. Provide an allowlist (optional) with `MDNS_ALLOWED_HOSTS`.
3. Run the script from the repo root; it will redact IP/MAC addresses and summarize
   packet captures so the output is safe to commit.

## Handling journald rate limits locally

Systemd's journal may drop frequent Avahi or network diagnostics if its rate limits are
hit. Developers who need more verbose local capture can adjust the runtime configuration
without editing repository files by running:

```bash
sudo mkdir -p /etc/systemd/journald.conf.d
cat <<'CONF' | sudo tee /etc/systemd/journald.conf.d/sugarkube-debug.conf
[Journal]
RateLimitIntervalSec=30s
RateLimitBurst=2000
CONF
sudo systemctl restart systemd-journald
```

These overrides live on the workstation only; do not commit them to the image or this
repository. Tune `RateLimitIntervalSec` and `RateLimitBurst` to match your hardware if
you still encounter dropped entries.
