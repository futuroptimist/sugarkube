# 2025-11-11 mDNS discovery outage

## Summary
Follower ignored valid mDNS server due to strict avahi-resolve requirement during early Avahi instability.

## Impact
Multi-node discovery intermittently fails; cluster nodes stay disconnected.

## Timeline (UTC)
- 2025-11-11 04:36:54 — sugarkube0 starts; D-Bus flaky; publishes after alive(401); self-check confirmed.
- 2025-11-11 04:38:51 — server publish confirmed.
- 2025-11-11 04:40:40 — sugarkube1 starts; fails to join due to avahi-resolve gate.

## Root cause
Discovery selected resolve_ok as a hard gate; avahi-resolve can fail even when NSS works (seen on Pi platforms).

## Contributing factors
Avahi D-Bus transitions at boot; follower did not leverage “publish-on-alive” data; absence of TXT IPs.

## Fix
(1) accept NSS fallback; (2) publish ip4/ip6 in TXT and prefer TXT IPs; (3) keep D-Bus fallback and publish-on-alive introduced in #1731/#1733.

## Prevention
Tests added for NSS fallback, TXT IP, and D-Bus CLI browse interplay; logs now show accept_path.

## Appendix
Relevant log snippets and commands.
