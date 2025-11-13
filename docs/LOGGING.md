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

### Avahi journal diagnostics

When mDNS self-checks fail `scripts/net_diag.sh` emits
`event=avahi_journal_dump` entries. The first log item captures the most recent
`journalctl -u avahi-daemon` output (200 lines by default, overridable via
`AVAHI_JOURNAL_LINES`). Subsequent entries summarize whether Avahi reported:

- `pattern=successfully_established`: service registration lines such as
  `Service "foo" ... successfully established`.
- `pattern=failed_to_read_service_file`: parse errors caused by unreadable
  `.service` files.
- `pattern=failed_to_parse_xml`: XML validation failures while loading service
  definitions.

These highlights make it clear whether Avahi accepted the service definition or
rejected it while still preserving the raw journal for deeper inspection.

Avahi only notices new `.service` files when they are moved atomically into
`/etc/avahi/services/`. Use `install -m0644` (or copy into a temporary path and
rename) so the daemon never parses half-written XML. Because the daemon runs in
a chroot, journal messages cite `/services/<name>.service`; prepend
`/etc/avahi` when locating the file on the host.

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

## End-of-run summaries

`pi_node_verifier.sh` appends a Markdown block to `/boot/first-boot-report.txt`
whenever logging is enabled. The generated table mirrors the CLI output and the
JSON export, so you can diff results across runs:

```markdown
### Verifier Checks

| Check | Status |
| --- | --- |
| kube_proxy_dataplane | pass |
| k3s_node_ready | fail |
```

Status semantics match the console output:

- `pass` — prerequisite satisfied. Expect this once kube-proxy runs in nft mode
  (GA as of Kubernetes v1.33).
- `fail` — intervention required before continuing the runbook.
- `skip` — the probe could not run and should be revisited later.

When nftables mode is configured the `kube_proxy_dataplane` check logs `pass`,
confirming that the nft binary is available and the configuration is
consistent. The first-boot preflight also emits a `k3s-preflight` journal entry
(`kube-proxy mode=nftables nft=yes`) so you can confirm the dataplane without
opening the verifier report.
