# 2025-10-25: mDNS self-check invisible despite avahi-publish logs

## Symptoms
- `k3s-discover.sh` logged that `avahi-publish` established the service, yet peers could not discover `_k3s-CLUSTER-ENV._tcp` entries.
- `avahi-browse -rt _k3s-*.local` returned no instances for the publishing host even though the publisher reported success.
- New control-plane nodes timed out waiting for bootstrap leadership because the service advertisement never became visible.

## Root cause
- The discovery flow trusted `avahi-publish` log lines such as "Established under name …" to infer success when the CLI self-check failed.
- In cases where Avahi dropped the advertisement before browse queries completed, the Python self-check exited non-zero but `k3s-discover.sh` suppressed the failure and proceeded.

## Fix
- Replace the Python helper with a POSIX `mdns_selfcheck.sh` wrapper that shells out to `avahi-browse` and `avahi-resolve` with exponential backoff and jitter.
- Teach `k3s-discover.sh` to invoke the new shell helper after publishing and surface non-zero exit codes instead of assuming success from log messages.
- Add Bats coverage for the shell helper so failures in parsing browse output or IPv4 mismatches block the flow.

## Verification steps
1. Publish a bootstrap service and run `scripts/mdns_selfcheck.sh` with the expected host and IPv4; confirm it reports `outcome=ok`.
2. Stop the publisher and rerun the self-check to observe repeated `outcome=miss` logs followed by `outcome=fail`.
3. Exercise `scripts/k3s-discover.sh --test-bootstrap-publish` on a lab node and confirm the script exits non-zero if the self-check never observes the advertisement.

## References
- `scripts/mdns_selfcheck.sh`
- `scripts/k3s-discover.sh`
- `tests/bats/mdns_selfcheck.bats`
