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
  back to a relaxed match. The flag also emits per-attempt timing so you can
  differentiate between RFC 6762 retransmissions and genuine packet loss.
- `SUGARKUBE_MDNS_DBUS=0` forces the CLI mDNS validator; omit or set to `1`
  to keep the default D-Bus backend (see [DBUS.md](DBUS.md)).
- `SUGARKUBE_MDNS_WIRE_PROOF=1` (default) requires the discovery flow to
  confirm D-Bus answers with a passive capture of UDP/5353. Logs show the
  `mdns_wire_proof` event so you can trace when Sugarkube trusted or rejected
  multicast responses.

## Structured log fields

Most discovery and absence-gate messages share a common set of fields:

- `attempts` – ordinal counter for retry loops, usually capped at 5 by the
  helpers.
- `last_method` – whether the D-Bus or CLI backend produced the most recent
  result.
- `ms_elapsed` – milliseconds elapsed since the helper started. Successful
  mDNS resolves on a quiet LAN typically land between 150 and 400 ms while
  the absence gate (triggered after `just wipe`) may run 2–5 seconds to
  collect the required consecutive misses.
- `wire_proof_status` – summary of the RFC 6762 wire capture. Expect `absent`
  when `SUGARKUBE_MDNS_WIRE_PROOF=1` and the passive sniff finds no stray
  responses.

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
