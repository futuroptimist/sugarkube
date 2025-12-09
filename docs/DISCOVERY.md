# K3s Discovery Flow

The Sugarkube discovery system enables automatic cluster formation without manual coordination. Nodes discover each other via mDNS and use deterministic leader election to prevent split-brain scenarios.

## Discovery Flow Overview

The discovery process follows this sequence:

1. **Baseline**: Node starts with no cluster knowledge
2. **Publish**: Advertise bootstrap service via mDNS
3. **Self-check**: Verify own advertisement is visible
4. **Election**: Run deterministic leader election if no server found
5. **Install/Join**: Bootstrap new cluster or join existing server

## Detailed Flow

### Phase 1: Initial Discovery
- Node attempts to discover existing API servers via mDNS
- If server found: proceed to join as agent
- If no server: continue to bootstrap phase

### Phase 2: Bootstrap Advertisement
- Publish bootstrap service with `phase=bootstrap` and `state=pending`
- Wait for `DISCOVERY_WAIT_SECS` (default: 2 seconds)
- Run self-check to confirm advertisement visibility

### Phase 3: Leader Election
- If self-check fails or no clear leader: run `scripts/elect_leader.sh`
- Election uses deterministic key (FQDN + primary MAC address)
- Only lexicographically smallest node proceeds with bootstrap
- Non-winners become followers and continue polling for servers

### Phase 4: Cluster Formation
- **Single node**: Install server with SQLite datastore
- **Multi-node**: Install server with etcd datastore (cluster init)
- **Followers**: Join existing server as agents

## Configuration

### Environment Variables
- `SERVERS_DESIRED`: Target number of control-plane nodes (default: 1)
- `DISCOVERY_ATTEMPTS`: Max discovery attempts (default: 10)
- `DISCOVERY_WAIT_SECS`: Wait between attempts (default: 2)
- `ELECTION_HOLDOFF`: Wait after election before bootstrap (default: 3)
- `FOLLOWER_REELECT_SECS`: Re-election interval for followers (default: 30)

### Logging Controls
- `LOG_LEVEL`: Control verbosity (info/debug/trace)
- `SUGARKUBE_DEBUG_MDNS=1`: Enable detailed mDNS diagnostics
- See [LOGGING.md](LOGGING.md) for details

### mDNS Diagnostics and Resilience
- **Automatic Retry**: avahi-browse retries once after 1-2s on failure
- **D-Bus Fallback**: Attempts gdbus/busctl ServiceBrowser if avahi-browse fails
- **Journal Logging**: On failure, dumps last 200 lines of avahi-daemon journal
- **Interface Pinning**: Set `ALLOW_IFACE=eth0` to pin queries to specific interface
- **Detailed Logging**: Exit codes and stderr are logged for all avahi-browse attempts
- **Offline-friendly checks**: Run `MDNS_DIAG_STUB_MODE=1 scripts/mdns_diag.sh` to
  exercise argument handling and environment overrides without Avahi installed; the
  stub emits a quick summary and exits cleanly on constrained hosts.

## Troubleshooting

### Common Issues

#### Split-brain Prevention
- **Symptom**: Multiple nodes bootstrap simultaneously
- **Cause**: Race condition in discovery or election failure
- **Resolution**: See [Split-brain Bootstrap Election](outages/2025-10-25-split-brain-bootstrap-election.md)

#### mDNS Self-check Failures
- **Symptom**: Bootstrap advertisement not visible to self
- **Cause**: Network issues, Avahi configuration, or timing
- **Resolution**: See [mDNS Self-check Issues](outages/2025-10-22-k3s-mdns-self-check.json) and [Invisible mDNS Self-check](outages/2025-10-25-mdns-selfcheck-invisible.md)

#### Avahi Service Resolution
- **Symptom**: Services not resolving or timing out
- **Cause**: Network configuration, firewall rules, or Avahi daemon issues
- **Resolution**: See [Avahi Baseline Issues](outages/2025-10-25-avahi-baseline.md) and [Avahi Service XML Broken](outages/2025-10-22-k3s-avahi-service-xml-broken.json)

#### Address Mismatch
- **Symptom**: Discovered address doesn't match expected hostname
- **Cause**: Network configuration or DNS resolution issues
- **Resolution**: See [Address Mismatch](outages/2025-10-24-k3s-discover-address-mismatch.json) and [mDNS Address Omission](outages/2025-10-24-k3s-discover-mdns-address-omission.json)

#### UDP Port Conflicts
- **Symptom**: mDNS traffic blocked or conflicting
- **Cause**: Firewall rules or other services using UDP/5353
- **Resolution**: See [UDP 5353 Conflict](outages/2025-10-25-udp-5353-conflict.md)

#### Election and Leadership Issues
- **Symptom**: Nodes fail to elect leader or follow incorrect leader
- **Cause**: Election logic failures or network partitions
- **Resolution**: See [Bootstrap Split-brain](outages/2025-10-22-k3s-bootstrap-split-brain.json) and [Mid-election Server](outages/2025-10-22-k3s-discover-mid-election-server.json)

#### Network Interface Problems
- **Symptom**: Discovery fails on specific network interfaces
- **Cause**: Interface selection or configuration issues
- **Resolution**: See [iptables Tooling](outages/2025-10-25-iptables-tooling.md) and [Avahi Address Issues](outages/2025-10-24-k3s-discover-avahi-address.json)

### Detailed Outage References

#### Core Discovery Issues
- [Split-brain Bootstrap Election](outages/2025-10-25-split-brain-bootstrap-election.md) - Deterministic election prevents multiple bootstraps
- [Bootstrap Split-brain](outages/2025-10-22-k3s-bootstrap-split-brain.json) - Race condition in bootstrap advertisement
- [Mid-election Server](outages/2025-10-22-k3s-discover-mid-election-server.json) - Server appears during election process

#### mDNS and Avahi Issues
- [mDNS Self-check Issues](outages/2025-10-22-k3s-mdns-self-check.json) - Self-check validation failures
- [Invisible mDNS Self-check](outages/2025-10-25-mdns-selfcheck-invisible.md) - Advertisement not visible despite publish success
- [Avahi Baseline Issues](outages/2025-10-25-avahi-baseline.md) - Bookworm Avahi configuration changes
- [Avahi Service XML Broken](outages/2025-10-22-k3s-avahi-service-xml-broken.json) - Service definition parsing errors
- [UDP 5353 Conflict](outages/2025-10-25-udp-5353-conflict.md) - Port conflicts with other mDNS services

#### Address and Resolution Issues
- [Address Mismatch](outages/2025-10-24-k3s-discover-address-mismatch.json) - Discovered vs expected addresses
- [mDNS Address Omission](outages/2025-10-24-k3s-discover-mdns-address-omission.json) - Missing address in mDNS records
- [Avahi Address Issues](outages/2025-10-24-k3s-discover-avahi-address.json) - Avahi address resolution problems
- [Hostname Address Issues](outages/2025-10-24-k3s-discover-mdns-hostname-address.json) - Hostname to address mapping

#### Timeout and Retry Issues
- [Avahi Timeout](outages/2025-10-23-k3s-discover-avahi-timeout.json) - Avahi operation timeouts
- [mDNS Browse Timeout](outages/2025-10-24-k3s-discover-mdns-browse-timeout.json) - Browse operation timeouts
- [mDNS Browse Fallback](outages/2025-10-24-k3s-discover-mdns-browse-fallback.json) - Fallback mechanisms
- [Server Retry Logic](outages/2025-10-24-k3s-discover-mdns-server-retry.json) - Server discovery retry behavior

#### Logging and Debugging Issues
- [Attempt Logging Misleading](outages/2025-10-22-k3s-discover-attempt-logging-misleading.json) - Misleading log messages
- [mDNS Helper Timestamps](outages/2025-10-25-mdns-helper-timestamps.json) - Timestamp logging issues
- [Host Mismatch Logging](outages/2025-10-25-mdns-host-mismatch-logging.json) - Hostname mismatch logging
- [Fallback Logging](outages/2025-10-25-mdns-self-check-fallback-logging.json) - Fallback mechanism logging

#### Configuration and Environment Issues
- [Cluster Environment Case](outages/2025-10-24-k3s-discover-mdns-cluster-env-case.json) - Environment variable case sensitivity
- [Missing Phase](outages/2025-10-24-k3s-discover-mdns-missing-phase.json) - Missing phase information
- [Double Local](outages/2025-10-24-k3s-discover-mdns-double-local.json) - Duplicate .local suffixes
- [Control Character Issues](outages/2025-10-25-mdns-self-check-control-char.json) - Control character handling

### Debugging Steps

1. **Enable verbose logging**:
   ```bash
   LOG_LEVEL=debug SUGARKUBE_DEBUG_MDNS=1 scripts/k3s-discover.sh
   ```

2. **Check mDNS services**:
   ```bash
   avahi-browse -at
   avahi-resolve -n sugarkube0.local
   ```

3. **Verify network connectivity**:
   ```bash
   ping sugarkube0.local
   nmap -sU -p 5353 sugarkube0.local
   ```

4. **Test election logic**:
   ```bash
   SUGARKUBE_SERVERS=3 scripts/elect_leader.sh
   ```

5. **Manual self-check**:
   ```bash
   SUGARKUBE_EXPECTED_HOST=sugarkube0.local scripts/mdns_selfcheck.sh
   ```

### Recovery Procedures

#### Reset Discovery State
- Stop all `avahi-publish` processes
- Clear any existing cluster state
- Restart discovery with fresh election

#### Force Single-node Bootstrap
- Set `SERVERS_DESIRED=1`
- Ensure no other nodes are advertising services
- Run discovery with `LOG_LEVEL=trace`

#### Network Isolation Testing
- Use `iptables` to block UDP/5353 between nodes
- Test election behavior in isolation
- Verify fallback mechanisms work correctly

## Related Documentation

- [LOGGING.md](LOGGING.md): Log levels and debug toggles
- [DBUS.md](DBUS.md): Optional D-Bus mDNS validator
- [TESTING.md](TESTING.md): Test infrastructure and debugging
- [Outage Catalog](outage_catalog.md): Complete list of known issues
