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
- `SUGARKUBE_MDNS_WIRE_PROOF=1` adds an explicit TCP probe to the discovery
  loop. When enabled the scripts refuse to call a server ready until port 6443
  answers, mirroring the readiness gate in the runbook.

Each discovery log line carries an `ms_elapsed` field representing the time
between starting the Avahi browse/resolve cycle and receiving a final answer.
Values under 200 ms are typical on a quiet LAN with K3s’ default
Flannel VXLAN overlay; spikes or timeouts point to multicast flooding or
pod-network reachability issues that need investigation.

RFC 6763 explicitly allows human-readable service instance names with spaces
and punctuation. Treat the instance string as display text only—matching must
verify the service type, TXT attributes, and the SRV record that resolves to
the authoritative host.

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
