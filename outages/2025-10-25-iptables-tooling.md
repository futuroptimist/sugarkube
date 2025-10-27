# 2025-10-25: Missing iptables tooling blocked K3s networking

## Symptoms
- Freshly provisioned nodes failed to schedule workloads that required ClusterIP services.
- `k3s check-config` reported missing iptables support and the kube-proxy logs flagged nftables incompatibilities.
- Pods with hostNetwork enabled could not reach other services on the cluster overlay.

## Root cause
- Some images skipped installing the `iptables` and `ip6tables` utilities when the base OS transitioned to nftables-by-default builds.
- The K3s installer assumes the commands exist even when using the nft backend, so kube-proxy silently failed to program rules.

## Fix
- Added an install helper that guarantees both `iptables` and `ip6tables` are present before invoking the K3s installer.
- Logged the detected backend mode (`nft` or `legacy`) and version to make follow-up diagnostics easier.
- Wired the helper into the bootstrap flow so every control-plane or agent install runs the check first.

## Verification steps
1. Run `/opt/sugarkube/scripts/k3s-install-iptables.sh` and confirm the log reports `event=iptables_check` with `installed=no` on already-provisioned systems.
2. Execute the standard bootstrap (`k3s-discover.sh`) on a fresh node and verify the helper logs prior to the `curl https://get.k3s.io` invocation.
3. Confirm `k3s check-config` no longer warns about missing iptables tooling and kube-proxy programs rules successfully.

## References
- [K3s documentation: iptables backend requirements](https://docs.k3s.io/advanced#iptables-backend-requirements)
- [K3s issue tracker: Handling nftables vs legacy backends](https://github.com/k3s-io/k3s/issues/703)
