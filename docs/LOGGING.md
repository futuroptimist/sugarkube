# Sugarkube logging overview

Sugarkube shell utilities emit structured `key=value` pairs so logs are
machine-parseable while still being readable during interactive debugging.

## Runtime toggles

- `LOG_LEVEL` controls verbosity for scripts that source `scripts/log.sh`.
  - Valid values: `info` (default), `debug`, `trace`.
  - `debug` enables per-attempt summaries such as mDNS discovery retries.
  - `trace` includes the raw Avahi command output and backoff calculations.
- `SUGARKUBE_DEBUG_MDNS=1` keeps the existing network diagnostics behaviour in
  `k3s-discover.sh`, dumping detailed Avahi traces whenever a self-check fails or
  falls back to a relaxed match.

Set the variables just for a single command:

```bash
LOG_LEVEL=debug SUGARKUBE_DEBUG_MDNS=1 scripts/k3s-discover.sh
```

The `info` level keeps successful bootstrap runs to a handful of high-signal
lines while still surfacing warnings and errors.
