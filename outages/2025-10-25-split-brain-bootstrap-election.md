# 2025-10-25: Split-brain during bootstrap without deterministic election

## Reproduction
- Bring up two freshly imaged control-plane nodes (`sugarkube0`, `sugarkube1`).
- Block mDNS responses between the peers (e.g., drop UDP/5353 with `iptables -A INPUT -p udp --dport 5353 -j DROP`).
- Start `scripts/k3s-discover.sh` simultaneously on both hosts.
- Both nodes fail to detect an existing API server and independently publish bootstrap advertisements before the other can respond.

## Root cause
- The discovery loop relied solely on opportunistic mDNS activity and a bootstrap advertisement race.
- When Avahi browsing stalled or returned stale results, multiple nodes concluded they should initialize the datastore, producing an etcd split-brain.

## Behavior change
- Added `scripts/elect_leader.sh` to derive a deterministic node key (FQDN plus primary MAC) and select the lexicographically smallest peer from the expected hostname set.
- Updated `scripts/k3s-discover.sh` to run the election whenever no API server is confirmed, hold for `ELECTION_HOLDOFF` seconds, and only allow the elected node to proceed with bootstrap.
- Non-winning nodes now log `event=election outcome=follower` and keep polling for an existing server instead of advertising a competing bootstrap attempt.

## Verification steps
1. On an isolated node, export `SUGARKUBE_SERVERS=3` and confirm `scripts/elect_leader.sh` prints `winner=yes` on `sugarkube0` but `winner=no` on `sugarkube1`.
2. Start `scripts/k3s-discover.sh` on two nodes with mDNS suppressed; observe only the elected node logs `event=election outcome=winner` and bootstraps after the holdoff, while the peer remains a follower until the API server appears.
3. Re-enable mDNS, rerun discovery, and verify followers immediately detect the server advertisement and join without attempting bootstrap.
