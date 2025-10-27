# Optional D-Bus mDNS self-check

`scripts/mdns_selfcheck.sh` supports an alternative validator that uses the
system D-Bus to query Avahi directly. The default CLI path (`avahi-browse`
followed by `avahi-resolve`) remains unchanged, so existing CI and automation do
not need any additional dependencies.

## Enabling the D-Bus backend

Set `SUGARKUBE_MDNS_DBUS=1` when invoking the self-check to opt in to the D-Bus
code path:

```bash
SUGARKUBE_MDNS_DBUS=1 \
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
the D-Bus helper exits with status `2` and `mdns_selfcheck.sh` transparently
falls back to the CLI implementation.

## Integration with discovery flow

The D-Bus validator is automatically used by `scripts/k3s-discover.sh` when
`SUGARKUBE_MDNS_DBUS=1` is set, providing more reliable mDNS validation during
the bootstrap and server advertisement phases.

## Caveats

- The D-Bus helper requires access to the system bus and the Avahi D-Bus
  service. These calls are typically blocked in sandboxed environments; the CLI
  fallback still works there.
- Only the subset of Avahi features used by Sugarkube are implemented. Any
  unexpected D-Bus failures bubble up as non-zero exits so the calling workflow
  can surface useful diagnostics.
- Performance: D-Bus calls may be faster than CLI tools in environments with
  high mDNS traffic, but the difference is typically negligible.
