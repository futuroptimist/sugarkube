# Sugarkube Debug Logs

This directory stores sanitized diagnostics that are safe to commit for collaboration. The
`logs/debug-mdns.sh` helper captures mDNS and k3s connectivity details while redacting addresses and
filtering hostnames to an allowlist. Outputs can be committed as
`logs/debug-mdns_YYYY-MM-DDTHH:MM:SS-07:00.log.sanitized` without leaking WAN IPs or local topology.

## Allowlisting hostnames

The script keeps only `_k3s-sugar-dev._tcp` service entries plus an allowlist of hostnames. By
default, the allowlist contains `sugarkube0.local`, `sugarkube1.local`, and `sugarkube2.local`.
Override it at runtime if you need to include a different set:

```bash
MDNS_ALLOWED_HOSTS="sugarkube0.local lab-node.local" ./logs/debug-mdns.sh > logs/debug-mdns_$(date -Iseconds).log.sanitized
```

## Running the script locally

1. Ensure `avahi-browse`, `avahi-resolve`, and `tcpdump` are installed locally (or available via
   `sudo`).
2. Run the script from the repo root. It summarizes tcpdump, ping, and curl operations instead of
   emitting raw packets. Any IP or MAC addresses that appear in command output are redacted.
3. Review the sanitized log to confirm only allowlisted hostnames and redacted tokens appear before
   sharing or committing it.

## Capturing boot logs

When `SAVE_DEBUG_LOGS=1` is exported during a `just up` bootstrap run, this directory also collects
sanitized `just up` logs. Files are named with the UTC timestamp, the checked-out commit hash, the
hostname, and the environment to make it easy to pair logs from multiple nodes. Secrets and external
IP addresses are redacted automatically before they are written here.

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
