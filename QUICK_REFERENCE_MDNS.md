# Quick Reference: mDNS Discovery (2025-11-15 Fixes)

## What Changed

**Before (broken):**
```bash
avahi-browse --parsable --terminate --ignore-local --resolve _k3s-sugar-dev._tcp
# Only checked cache, ignored local services → 0 results on fresh boot
```

**After (fixed):**
```bash
avahi-browse --parsable --resolve _k3s-sugar-dev._tcp
# Waits for network, discovers all services → works on fresh boot
```

## Environment Variables

| Variable | Default | What It Does |
|----------|---------|--------------|
| `SUGARKUBE_MDNS_NO_TERMINATE` | `1` | **1** = wait for network (recommended), **0** = cache only |
| `SUGARKUBE_MDNS_QUERY_TIMEOUT` | `10.0` | Seconds to wait for mDNS responses |
| `SUGARKUBE_DEBUG` | unset | Enable detailed debug logging |

## Quick Test

### CI/Local safety net

- Integration tests now rely on the hermetic Avahi CLI stubs under `tests/fixtures/avahi_stub`.
- The roundtrip self-check fails (instead of skipping) if `avahi-{publish,browse,resolve}`
  are missing, guaranteeing we always exercise mDNS discovery logic.
- The mdns_ready publish/browse path uses the stub automatically so local discovery stays
  deterministic even without system Avahi packages.

### Verify bootstrap node is advertising:

```bash
# On sugarkube0 (after `just up dev`)
avahi-browse --parsable --resolve _k3s-sugar-dev._tcp
# Press Ctrl+C after 5 seconds
# Should show: =;eth0;IPv4;k3s-sugar-dev@sugarkube0;_k3s-sugar-dev._tcp;...
```

### Verify joining node can discover:

```bash
# On sugarkube1
avahi-browse --parsable --resolve _k3s-sugar-dev._tcp
# Press Ctrl+C after 5 seconds
# Should show services from sugarkube0
```

## Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| "got 0 normalized lines" | Multicast blocked | Check firewall/network |
| "service not found" | Avahi not running | `sudo systemctl start avahi-daemon` |
| TypeError in logs | Old code | Pull latest fixes (commit f32d234+) |
| Discovery slow (30+ sec) | Network congestion | Increase timeout: `SUGARKUBE_MDNS_QUERY_TIMEOUT=30` |

## When to Use Cache-Only Mode

Set `SUGARKUBE_MDNS_NO_TERMINATE=0` to use `--terminate` flag (cache only):

✅ **Good for:**
- Quick lookups when nodes have been running for a while
- Checking what's already cached
- Performance testing

❌ **Bad for:**
- Initial cluster formation (cache is empty)
- Discovering newly started services
- Troubleshooting discovery issues

**Default is network mode for reliability.**

## See Also

- **Full troubleshooting:** `docs/mdns_troubleshooting.md`
- **Setup guide:** `docs/raspi_cluster_setup.md`
- **Summary:** `MDNS_FIXES_SUMMARY.md`
- **Outage logs:** `outages/2025-11-15-mdns-*.json`
