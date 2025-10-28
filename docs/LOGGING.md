# Sugarkube logging overview

Sugarkube shell utilities emit structured `key=value` pairs so logs are
machine-parseable while still being readable during interactive debugging.

## Log levels

- `LOG_LEVEL` controls verbosity for scripts that source `scripts/log.sh`.
  - Valid values: `info` (default), `debug`, `trace`.
  - `info`: High-signal events only (bootstrap outcomes, warnings, errors)
  - `debug`: Per-attempt summaries including mDNS discovery retries and election results
  - `trace`: Raw Avahi command output, backoff calculations, and detailed state transitions

## Debug toggles

- `SUGARKUBE_DEBUG_MDNS=1` enables detailed network diagnostics in
  `k3s-discover.sh`, dumping Avahi traces whenever a self-check fails or falls
  back to a relaxed match.
- `SUGARKUBE_MDNS_DBUS=0` forces the CLI mDNS validator; omit or set to `1`
  to keep the default D-Bus backend (see [DBUS.md](DBUS.md)).
- `SUGARKUBE_MDNS_WIRE_PROOF=1` instructs the discovery helpers to capture a
  short burst of multicast DNS traffic and ensure that RFC 6762 responses for
  the target host actually hit the wire. Set it to `0` to skip the
  tcpdump-based verification when Avahi is running in a sandbox or when
  `tcpdump` is prohibited.

## Timing fields in the logs

Many discovery log lines include an `ms_elapsed` field. It reports the wall
clock milliseconds spent inside the relevant check—from the first Avahi browse
through socket readiness probes. On a quiet LAN where K3s defaults (Flannel
overlay with VXLAN encapsulation) are healthy, expect:

- Presence confirmations (`mdns_selfcheck outcome=confirmed`) to resolve in
  roughly **120–400 ms**, covering the Avahi browse and the 6443 readiness gate
  that opens a TCP socket against the API server.
- Absence gates after a `just wipe` or environment teardown to take **1.5–3.0
  s** because Sugarkube requires two consecutive negative D-Bus reads and, when
  enabled, one wire-level proof before declaring that an advertisement is gone.

Higher values usually mean retransmissions on the LAN or slow responses from
the mDNS publisher.

## Usage examples

Set variables for a single command:

```bash
LOG_LEVEL=debug SUGARKUBE_DEBUG_MDNS=1 scripts/k3s-discover.sh
```

Enable trace logging for troubleshooting:

```bash
LOG_LEVEL=trace scripts/k3s-discover.sh
```

The `info` level keeps successful bootstrap runs to a handful of high-signal
lines while still surfacing warnings and errors. Use `debug` or `trace` when
investigating discovery failures or election behavior.
