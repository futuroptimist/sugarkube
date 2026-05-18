# Sugarkube HA staging outage: DHCP IP reassignment and stale durable IP coupling

- **Date:** 2026-05-18
- **Scope:** Sugarkube HA staging cluster (`sugarkube3.local`, `sugarkube4.local`, `sugarkube5.local`)
- **Impact:** staging control plane unhealthy; DSPACE staging unavailable until cluster rebuild and redeploy

## Summary
A home power outage caused DHCP to reassign LAN IPs for all three HA staging control-plane nodes. Sugarkube automation had persisted raw LAN IP values into durable k3s identity/config paths (including TLS SAN inputs) where stable hostname identity (`<host>.local`) should have been preferred. After DHCP churn, k3s and embedded etcd could not converge cleanly, leaving control-plane services stuck and Kubernetes unavailable.

A second, parallel operator hazard also surfaced: `just up env=staging` was parsed literally as `env=staging` (not as named argument syntax), generating malformed discovery state and stale Avahi service files that required manual cleanup before stable discovery resumed.

## Detection and symptoms
- `k3s` on HA nodes stuck in `activating (start)`.
- embedded etcd emitted repeated errors, including:
  - `transport: authentication handshake failed: context deadline exceeded`
  - `failed to publish local member to cluster through raft`
  - `etcdserver: request timed out`
- one installed node had stale raw-IP SAN input like `--tls-san 192.168.86.37` while current `eth0` was e.g. `192.168.86.40`.

## Contributing issue: named-env parsing footgun
`just up env=staging` was treated as a positional literal string instead of named argument semantics, causing malformed discovery values such as:
- `environment=env=staging`
- `service_type=_k3s-sugar-env=staging._tcp`
- `<txt-record>env=env=staging</txt-record>`
- `/etc/avahi/services/k3s-sugar-env=staging.service`

Immediate workaround used during recovery:
- `just up staging`
- `just save-logs staging`

Required cleanup for stale malformed Avahi service file:
- `sudo rm -f /etc/avahi/services/k3s-sugar-env=staging.service`
- `sudo systemctl restart avahi-daemon`

## Recovery journey
1. GHCR chart pull initially failed with `403 denied: denied` due to expired GitHub classic PAT (`read:packages`).
2. PAT rotated; GHCR login restored.
3. Chart access confirmed with:
   - `helm show chart oci://ghcr.io/democratizedspace/charts/dspace --version 3.0.0`
4. Kubernetes still unreachable because k3s control plane remained unhealthy.
5. Since state preservation was unnecessary, k3s was wiped and rebuilt across **all three** HA servers (not single-node repair):
   - `sugarkube3.local`, `sugarkube4.local`, `sugarkube5.local`
6. Rebuild used positional env invocation (`just up staging`).
7. Post-rebuild operations:
   - `just ha3-untaint-control-plane`
   - Traefik reinstall/verification
   - Cloudflare tunnel reinstall/verification
8. Fresh-cluster Helm nuance observed: `helm-oci-upgrade` failed with `UPGRADE FAILED: "dspace" has no deployed releases`; first path required `helm-oci-install`.
9. DSPACE `v3.0.1-rc.5` deployed successfully to staging; staging UI showed expected SHA/tag (e.g. `main-92a1bcb`).
10. Prod/apex intentionally remained on `v3.0.0`.

## Root cause
Sugarkube used DHCP-derived raw IPv4 values as part of durable cluster identity/certificate configuration where stable hostname identity should be primary. This made recovery sensitive to routine LAN address churn after power events.

## Prevention and corrective action in Sugarkube
- Default durable TLS SAN identity now uses hostname forms (`<hostname>.local` and short hostname) rather than raw LAN DHCP IPs.
- Raw node IP SAN support is retained only as explicit opt-in (`SUGARKUBE_TLS_SAN_INCLUDE_NODE_IP=1`) for deployments that require it.
- Discovery and operator-facing endpoints continue to prefer `.local` identities.
- Runtime node networking IP selection remains interface-based/deterministic where needed, but is not treated as durable identity.
