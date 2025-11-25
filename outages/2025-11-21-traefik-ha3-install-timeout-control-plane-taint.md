# Outage Report: Traefik install timeout on ha3 due to control-plane taints

**Date**: 2025-11-21
**Component**: Traefik install helper (ha3 dev topology)
**Severity**: Medium (ingress unavailable until manual intervention)
**Status**: Resolved

## Summary

In November 2025, `just traefik-install` repeatedly timed out with `context deadline exceeded`
when installing Traefik on the 3-node HA dev cluster. Traefik pods (and the k3s klipper-helm
Traefik addon jobs) could not be scheduled because all nodes carried control-plane NoSchedule
taints and there were no worker nodes.

## Impact

- Traefik installation via `just traefik-install` on the 3-node HA dev cluster failed.
- The dev cluster could not expose HTTP workloads via Traefik until the issue was debugged and
  fixed.

## Timeline

- Bring up a fresh 3-node HA dev cluster with `just up env=dev` / `just ha3`.
- Run `just traefik-install`; Helm reports `Error: context deadline exceeded` and `STATUS: failed`
  in `helm status traefik -n kube-system`.
- `kubectl -n kube-system get deploy,pods,svc,job | grep -i traefik` shows:
  - `deployment/traefik` with 0/1 available.
  - `pod/traefik-...` Pending.
  - `helm-install-traefik-*` and `helm-install-traefik-crd-*` jobs Pending.
- Scheduler events indicate `0/3 nodes are available: 3 node(s) had untolerated taint
  {node-role.kubernetes.io/control-plane: true}` for the Traefik pods and klipper-helm jobs.
- `just ha3-untaint-control-plane` prints that no taint is present even though the taint remains
  active, leaving no schedulable nodes.

## Root cause

- The dev HA topology uses three nodes with roles `control-plane,etcd,master` and no workers.
- k3s applies `node-role.kubernetes.io/control-plane=true:NoSchedule` taints to these nodes by
  default.
- Traefik’s Helm chart and the k3s klipper-helm Traefik addon jobs do not tolerate this taint.
- The existing `ha3-untaint-control-plane` recipe incorrectly checked for the taint and skipped
  removal, so the blocking taints stayed in place while the script claimed none were present.
- With every node tainted and no tolerations, Traefik pods remained Pending with `FailedScheduling`
  and `helm upgrade --install ... --wait` consistently timed out.
- The built-in k3s Traefik addon (helm-install-traefik and helm-install-traefik-crd jobs) was also
  stuck Pending for the same taint reason, representing a second potential Traefik source once the
  taints are cleared.

## Resolution

- Hardened `ha3-untaint-control-plane` to always attempt removal of
  `node-role.kubernetes.io/control-plane` and `node-role.kubernetes.io/master` taints, showing the
  before/after taint state for each node.
- Added preflight checks to `just traefik-install` that verify cluster reachability and fail fast
  when every node is control-plane-tainted with NoSchedule, instructing the user to run
  `just ha3-untaint-control-plane` first in the dev ha3 topology.
- Once the taints are removed and `just traefik-install` is re-run, Traefik can schedule on the HA
  nodes and the Helm install completes successfully.

## Lessons learned / follow-ups

- Clusters that only contain tainted control-plane nodes cannot schedule normal workloads unless
  taints are removed or workloads add tolerations.
- Helper commands like `ha3-untaint-control-plane` must actively remove taints and print the
  resulting taint state so they cannot silently misreport success.
- Preflight checks in recipes such as `traefik-install` help detect unschedulable topologies before
  waiting for long Helm timeouts.
- The built-in k3s Traefik addon should be considered when layering a custom Traefik install; it may
  need disabling in future topologies to avoid conflicting releases once taints are removed.
