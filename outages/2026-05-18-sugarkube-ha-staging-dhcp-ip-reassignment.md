# Sugarkube outage: HA staging control-plane failure after DHCP IP reassignment

- **Date:** 2026-05-18 (UTC)
- **Owner:** Sugarkube
- **Component:** k3s HA staging control-plane discovery/install path
- **Impact:** Staging control plane became unhealthy; Kubernetes API unavailable until cluster rebuild.

## Summary
A home power outage caused DHCP lease reassignment for `sugarkube3.local`, `sugarkube4.local`, and `sugarkube5.local`.
Sugarkube still persisted raw LAN IPs into durable k3s server install arguments (notably TLS SANs), so rebuilt/runtime assumptions diverged from stable `.local` identities. Once addresses changed, etcd/k3s stability degraded and the HA staging cluster could not recover in-place.

## What happened
1. Power returned and nodes came back with new LAN addresses.
2. Existing durable k3s state still referenced prior DHCP IP context (example: `--tls-san 192.168.86.37` persisted while host later owned `192.168.86.40` on `eth0`).
3. k3s stalled in `activating (start)` and etcd emitted:
   - `transport: authentication handshake failed: context deadline exceeded`
   - `failed to publish local member to cluster through raft`
   - `etcdserver: request timed out`
4. During recovery, GHCR chart pull initially failed (`403 denied: denied`) because a GitHub classic PAT with `read:packages` had expired.
5. After PAT rotation, GHCR access worked again (`helm show chart oci://ghcr.io/democratizedspace/charts/dspace --version 3.0.0`), but Kubernetes remained unreachable because control-plane health was still broken.

## Additional nuance discovered during recovery
A separate argument-parsing bug amplified confusion in staging runs:

- `just up env=staging` was parsed literally as `env=staging`.
- This produced malformed discovery state:
  - `environment=env=staging`
  - `service_type=_k3s-sugar-env=staging._tcp`
  - `<txt-record>env=env=staging</txt-record>`
  - `/etc/avahi/services/k3s-sugar-env=staging.service`
- Immediate workaround:
  - `just up staging`
  - `just save-logs staging`
- Required cleanup:
  - `sudo rm -f /etc/avahi/services/k3s-sugar-env=staging.service`
  - `sudo systemctl restart avahi-daemon`

## Recovery actions
1. Rotated GitHub PAT and restored GHCR auth.
2. Verified chart pull path independently of cluster health.
3. Confirmed control plane was unhealthy and state preservation was unnecessary.
4. Uninstalled/wiped/rebuilt **all three HA servers**, not just one:
   - `sugarkube3.local`
   - `sugarkube4.local`
   - `sugarkube5.local`
5. Rebuilt using positional environment invocations.
6. Removed control-plane taints: `just ha3-untaint-control-plane`.
7. Reinstalled/verified Traefik.
8. Reinstalled/verified Cloudflare tunnel.
9. On fresh cluster, `helm-oci-upgrade` failed with `UPGRADE FAILED: "dspace" has no deployed releases`; first deployment correctly used `helm-oci-install`.
10. Deployed DSPACE `v3.0.1-rc.5` to staging and verified expected staged SHA/tag (`main-92a1bcb`).
11. Left prod/apex intentionally pinned at `v3.0.0`.

## Root cause
Sugarkube conflated stable node identity with ephemeral network addressing by persisting DHCP-derived raw LAN IPs in durable k3s install/config surfaces where hostname-based identity (`<host>.local`, short hostname) should be default.

## Prevention and follow-up
- Sugarkube should treat hostname identity as durable default for TLS SANs/discovery endpoints.
- DHCP-derived raw IPv4 SANs must be opt-in only.
- Any required raw IP for runtime internals (`--node-ip`, `--advertise-address`, peer transport) must be deterministic, current, and regenerated at install/rebuild time.
- Keep Task 1 (`just up env=staging` parity) tracked separately and avoid named-form invocation until fixed.
