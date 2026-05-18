# Sugarkube HA staging outage after DHCP IP reassignment (2026-05-18)

## Summary
On **2026-05-18**, Sugarkube staging HA control-plane availability degraded after a home power outage caused DHCP lease reassignment across all three staging control-plane nodes:

- `sugarkube3.local`
- `sugarkube4.local`
- `sugarkube5.local`

The incident exposed a Sugarkube defect: durable k3s bootstrap/join identity still carried avoidable raw LAN IP coupling (for example via `--tls-san <old-ip>`), which became stale after DHCP churn.

## Impact
- Embedded etcd quorum became unhealthy.
- k3s remained in `activating (start)` on affected nodes.
- Kubernetes API became unreachable for staging operations.
- Staging deployment and operational workflows were blocked until full cluster rebuild.

Observed etcd/k3s errors included:
- `transport: authentication handshake failed: context deadline exceeded`
- `failed to publish local member to cluster through raft`
- `etcdserver: request timed out`

## Timeline and incident journey
1. GHCR Helm chart pull initially failed with `403 denied: denied` due to an expired classic GitHub PAT missing valid `read:packages` access.
2. PAT was rotated and GHCR Helm auth was restored.
3. Pull access verified with:
   - `helm show chart oci://ghcr.io/democratizedspace/charts/dspace --version 3.0.0`
4. Despite chart access recovery, Kubernetes remained unavailable because the HA k3s control-plane was unhealthy.
5. Since no state needed preservation, k3s was fully wiped and rebuilt across all HA servers (not a single-node fix):
   - `sugarkube3.local`
   - `sugarkube4.local`
   - `sugarkube5.local`
6. Cluster recovery used positional environment invocation as immediate mitigation:
   - `just up staging`
   - `just save-logs staging`
7. Control-plane taints were removed (`just ha3-untaint-control-plane`).
8. Traefik reinstall/verification completed.
9. Cloudflare tunnel reinstall/verification completed.
10. On fresh cluster, first attempt using OCI upgrade path failed as expected for no prior release:
    - `UPGRADE FAILED: "dspace" has no deployed releases`
11. Corrected to first-install path (`helm-oci-install`), then deployed DSPACE `v3.0.1-rc.5` to staging.
12. Staging UI reflected expected deployed SHA/tag (example: `main-92a1bcb`).
13. Production/apex intentionally remained on `v3.0.0`.

## Additional nuance captured from Task 1
A separate command-parsing issue increased recovery friction:

- `just up env=staging` was parsed literally as environment `env=staging`.
- This created malformed discovery state, including:
  - `environment=env=staging`
  - `service_type=_k3s-sugar-env=staging._tcp`
  - `<txt-record>env=env=staging</txt-record>`
  - `/etc/avahi/services/k3s-sugar-env=staging.service`

Immediate workaround:
- `just up staging`
- `just save-logs staging`

Cleanup required for malformed stale Avahi service files:
- `sudo rm -f /etc/avahi/services/k3s-sugar-env=staging.service`
- `sudo systemctl restart avahi-daemon`

## Root cause
Primary root cause is owned by Sugarkube internals:

- Home power outage triggered DHCP reassignment for staging HA nodes.
- Sugarkube installation/discovery behavior allowed durable k3s identity data to include stale raw LAN IPv4 values (for example `--tls-san 192.168.86.37`) that no longer matched node runtime address (for example node now on `192.168.86.40` on `eth0`).
- Stable `.local` node names existed, but avoidable durable IP identity coupling remained in generated configuration and install flags.

## Resolution
- Recovered service by full HA cluster reinstall/rejoin on all three staging control-plane nodes.
- Restored Helm/GHCR authentication by rotating expired PAT.
- Reinstalled staging ingress/tunnel dependencies and redeployed application workload.

## Prevention and follow-up direction
Sugarkube prevention work (Task 2 scope):
- Prefer stable host identity (`<hostname>.local` and short hostname) for durable TLS SAN and discovery/client endpoint identity.
- Remove DHCP-derived raw IPv4 TLS SAN defaults.
- Keep any required raw IP usage limited to runtime internals (`--node-ip`, `--advertise-address`, peer URLs), sourced deterministically from current interface state and regenerated safely.
- Keep optional raw-IP SAN support opt-in only.
- Add regression coverage so stale `192.168.x.x` durable SAN identity does not return as default.

Related later tasks:
- Task 3: `just cf-tunnel-install env=staging ...` parsing/tunnel naming hardening.
- Task 4: fresh-cluster OCI install-vs-upgrade behavior.
- Task 5/6: cross-repo operational documentation updates linking to this Sugarkube outage record.
