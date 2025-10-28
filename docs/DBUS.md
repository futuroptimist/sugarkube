# Optional D-Bus mDNS self-check

`scripts/mdns_selfcheck.sh` now prefers the system D-Bus backend when `gdbus`
is available, querying Avahi directly for deterministic results. The legacy CLI
path (`avahi-browse` followed by `avahi-resolve`) is still bundled and is used
whenever the D-Bus helper is unavailable or explicitly disabled.

The helpers surface the same telemetry regardless of backend. Discovery events
always log the elapsed time per probe (`ms_elapsed`) alongside the decision that
was made, which helps operators determine whether an mDNS lookup stalled on the
wire or failed locally. On an uncongested Layer 2 segment the D-Bus path usually
finishes in **20–120 ms**; noisy or lossy networks push the value higher and are
a prompt to fall back to the CLI helper or to enable the debug toggles described
below.

## Controlling the backend

To force the D-Bus path (even if a parent script opted out) export
`SUGARKUBE_MDNS_DBUS=1`:

```bash
SUGARKUBE_MDNS_DBUS=1 \
  SUGARKUBE_EXPECTED_HOST=sugarkube0.local \
  scripts/mdns_selfcheck.sh
```

Set `SUGARKUBE_MDNS_DBUS=0` to fall back to the CLI implementation:

```bash
SUGARKUBE_MDNS_DBUS=0 \
  SUGARKUBE_EXPECTED_HOST=sugarkube0.local \
  scripts/mdns_selfcheck.sh
```

When the flag is enabled and `gdbus` is present, the helper script will:

1. Create a `ServiceBrowser` for the expected service type via
   `org.freedesktop.Avahi.Server.ServiceBrowserNew`.
2. Resolve the expected instance with
   `org.freedesktop.Avahi.Server.ResolveService`.
3. Optionally call `org.freedesktop.Avahi.Server.ResolveHostName` to confirm the
   IPv4 address if one is specified.

If the environment does not expose `gdbus`, or Avahi rejects the D-Bus calls,
the helper exits with status `2` and `mdns_selfcheck.sh` transparently falls
back to the CLI implementation.

Enable `SUGARKUBE_DEBUG_MDNS=1` to emit the Avahi transactions and DNS-SD
payloads that back the decision. When the LAN path is the suspect, toggle
`SUGARKUBE_MDNS_WIRE_PROOF=1` to make the helper confirm reachability over TCP
port 6443 before declaring a discovery failure—mirroring the readiness gate
described in [docs/runbook.md](runbook.md#mdns-readiness-gates).

## Integration with discovery flow

`scripts/k3s-discover.sh` automatically opts into the D-Bus validator when
possible, providing more reliable mDNS validation during the bootstrap and
server advertisement phases.

When cleaning up a node (`just wipe`), the discovery flow performs a
double-negative absence check: it waits for mDNS advertisements to disappear,
then confirms the absence twice before continuing. This guards against transient
caches defined in [RFC 6762](https://datatracker.ietf.org/doc/html/rfc6762)
lingering on the segment and confusing the next bootstrap attempt.

## Caveats

- The D-Bus helper requires access to the system bus and the Avahi D-Bus
  service. These calls are typically blocked in sandboxed environments; the CLI
  fallback still works there.
- Only the subset of Avahi features used by Sugarkube are implemented. Any
  unexpected D-Bus failures bubble up as non-zero exits so the calling workflow
  can surface useful diagnostics.
- Performance: D-Bus calls may be faster than CLI tools in environments with
  high mDNS traffic, but the difference is typically negligible.
