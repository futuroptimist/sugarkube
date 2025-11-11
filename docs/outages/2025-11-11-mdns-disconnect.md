# 2025-11-11 mDNS discovery disconnect

## Summary
Follower ignored a valid mDNS server because discovery treated avahi-resolve success as a hard requirement while Avahi was unstable during boot.

## Impact
Multi-node discovery intermittently failed, leaving cluster nodes disconnected from the control plane.

## Timeline (UTC)
- **2025-11-11 04:36:54** — sugarkube0 starts; D-Bus flaky; publishes after alive(401); self-check confirmed. (GitHub)
- **2025-11-11 04:38:51** — Server publish confirmed. (GitHub)
- **2025-11-11 04:40:40** — sugarkube1 starts; fails to join due to avahi-resolve gate. (GitHub)

## Root Cause
Discovery selected `resolve_ok` as a hard gate even though avahi-resolve can fail while NSS succeeds, a behavior seen on Raspberry Pi platforms. (GitHub)

## Contributing Factors
Avahi D-Bus transitions at boot, the follower ignored publish-on-alive data, and TXT IPs were absent. (GitHub +1)

## Fix
1. Accept NSS fallback.
2. Publish IPv4/IPv6 addresses in TXT and prefer TXT IPs during discovery.
3. Retain the D-Bus fallback and publish-on-alive behavior introduced in #1731/#1733. (GitHub +1)

## Prevention
Added tests for NSS fallback, TXT IP fast path, and D-Bus CLI browse handling; logs now expose `accept_path`. (GitHub)

## Appendix
- Relevant log snippets and commands.
