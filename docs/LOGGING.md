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
