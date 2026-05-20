# Outage Report: HA staging outage after DHCP IP reassignment

**Date**: 2026-05-18  
**Component**: `scripts/k3s-discover.sh` and k3s durable install arguments/TLS SAN handling  
**Severity**: Critical (staging control plane unavailable)  
**Status**: Resolved

## Summary

A home power outage caused DHCP lease churn for `sugarkube3.local`, `sugarkube4.local`, and
`sugarkube5.local`. Sugarkube had durable configuration that coupled identity to raw LAN IPs
(e.g. `--tls-san 192.168.86.37`) instead of stable hostnames. After the addresses changed,
embedded etcd/k3s control-plane communication failed and staging became unreachable.

The incident also exposed a command parsing pitfall: `just up env=staging` was interpreted as
literal `env=staging` in some paths, producing malformed discovery state and Avahi artifacts.

## Impact

- HA staging control plane stuck in `activating (start)`.
- Embedded etcd raft communication unstable.
- Kubernetes API unreachable for workload operations.
- Staging deployment/recovery delayed by GHCR auth renewal and full control-plane rebuild.

## Detection and evidence

Representative failure logs during outage:

- `transport: authentication handshake failed: context deadline exceeded`
- `failed to publish local member to cluster through raft`
- `etcdserver: request timed out`

Malformed env parsing evidence (pre-fix behavior):

- `environment=env=staging`
- `service_type=_k3s-sugar-env=staging._tcp`
- `<txt-record>env=env=staging</txt-record>`
- `/etc/avahi/services/k3s-sugar-env=staging.service`

## Timeline and recovery

1. Home power event triggered DHCP reassignment on HA nodes (`sugarkube3/4/5.local`).
2. GHCR chart pull initially failed (`403 denied: denied`) due to expired classic PAT
   (`read:packages`); PAT rotated and login restored.
3. Pull validation succeeded with:
   - `helm show chart oci://ghcr.io/democratizedspace/charts/dspace --version 3.0.0`
4. Kubernetes remained unavailable because k3s control plane was unhealthy.
5. Because no state preservation was needed, k3s was uninstalled/wiped and rebuilt on all three
   HA server nodes (`sugarkube3.local`, `sugarkube4.local`, `sugarkube5.local`).
6. Immediate operator workaround used positional invocation:
   - `just up staging`
   - `just save-logs staging`
7. Stale malformed Avahi service file removed and daemon restarted:
   - `sudo rm -f /etc/avahi/services/k3s-sugar-env=staging.service`
   - `sudo systemctl restart avahi-daemon`
8. Control-plane taints removed via `just ha3-untaint-control-plane`.
9. Traefik and Cloudflare tunnel reinstalled and verified.
10. Fresh-cluster deploy path required install before upgrade (`helm-oci-install` first), then
    DSPACE `v3.0.1-rc.5` deployed successfully to staging.
11. Staging UI reflected expected deployment tag/SHA (e.g. `main-92a1bcb`).
12. Production/apex intentionally stayed on `v3.0.0`.

## Root cause

Two coupled issues:

1. **Durable identity/IP coupling defect in Sugarkube internals**: DHCP-derived IPv4 addresses were
   written into durable k3s install args (notably TLS SAN) where stable hostname identity should
   have been used by default.
2. **Named env parsing ambiguity**: `just up env=staging` could be preserved literally in some paths,
   generating malformed mDNS/Avahi metadata and complicating outage recovery.

## Resolution

- Sugarkube outage source-of-truth moved into this repository (`outages/` entry and JSON record).
- k3s discovery/install flow updated so durable TLS SAN defaults to stable hostname identity
  (`<hostname>.local` and short hostname) and no longer injects DHCP-derived node IP by default.
- Optional raw IP TLS SAN behavior retained as explicit opt-in only.
- Join/install endpoint preference shifted to hostname (`.local`) by default; optional IP preference
  retained behind explicit opt-in.
- Existing node runtime IP selection for internals remains deterministic/current via interface-based
  detection and node-IP drop-ins, so runtime networking can still use concrete current IP safely.

## Prevention

- Regression tests ensure stale `192.168.x.x` TLS SANs are not part of default durable identity.
- Tests assert hostname-based SAN presence and deterministic node IP selection behavior.
- Keep mDNS/Avahi identity hostname-based; reserve raw IP for explicit runtime requirements.

