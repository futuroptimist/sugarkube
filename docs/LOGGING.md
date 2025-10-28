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
- `SUGARKUBE_MDNS_WIRE_PROOF=1` asks the discovery flow to capture a short
  tcpdump window on UDP/5353 to prove that `_https._tcp` advertisements have
  stopped propagating. Disable it with `SUGARKUBE_MDNS_WIRE_PROOF=0` on hosts
  where packet capture is blocked.

The wire-proof toggle lines up with the double-negative absence gate described
in the recovery steps: two consecutive misses from the D-Bus path plus a quiet
wire window are required before Sugarkube treats an mDNS record as removed.

## Log fields

- `ms_elapsed` accompanies absence gates and self-checks. It records the total
  runtime (in milliseconds) between the start of a probe and the final decision.
  On a quiet wired LAN the D-Bus resolver usually completes in **120–400 ms**,
  and the wire-proof extension finishes inside **750 ms**. Multi-second values
  point to link congestion, packet loss, or RFC 6762 suppression timers firing
  repeatedly.

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
