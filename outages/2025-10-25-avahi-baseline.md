# 2025-10-25: Avahi baseline drifted on Bookworm

## Symptoms
- Raspberry Pi nodes running Raspberry Pi OS Bookworm no longer appeared via mDNS.
- `avahi-browse -at` on peers returned no workstation records for the affected host.
- `avahi-resolve -n <host>.local` timed out instead of resolving to the expected IPv4 address.

## Root cause
- The Avahi daemon defaulted to not advertising the host as a workstation, so Bonjour and other mDNS clients never learned about the node without a service announcement.
- On mixed Ethernet/WLAN systems we relied on Avahi's automatic interface selection, which occasionally chose the wrong interface or a downed WLAN during bootstrap, preventing the workstation record from being reachable.

## Fix
- Force `publish-workstation=yes` in `avahi-daemon.conf` (configurable via `SUGARKUBE_AVAHI_PUBLISH_WORKSTATION`).
- Pin `allow-interfaces` when a single operational target interface is detected or explicitly configured, preferring Ethernet and skipping WLAN whenever the guard file indicates it is down.
- Restart `avahi-daemon` only when the configuration file actually changes to avoid interrupting healthy advertisements.

## Verification steps
1. Run `avahi-browse -at` and confirm the host appears with the `_workstation._tcp` service on the intended interface.
2. Run `avahi-resolve -n <host>.local` from a peer and verify it resolves to the node's IP address.

## References
- [avahi-daemon.conf(5) — Avahi configuration options](https://manpages.debian.org/bookworm/avahi-daemon/avahi-daemon.conf.5.en.html)
- [Raspberry Pi documentation — Raspberry Pi OS Bookworm networking changes](https://www.raspberrypi.com/documentation/computers/os.html#bookworm)
