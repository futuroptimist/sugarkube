# Tailscale Remote Operations Design (Per-Node Membership)

## Overview

This design describes a reproducible, privacy-preserving way to operate a `sugarkube`
cluster remotely without changing its core LAN-based k3s bootstrap model.

Primary goal: a remote operator device (for example, a MacBook) can securely SSH to
individual `sugarkube<n>` nodes over a shared tailnet.

This is a public design note. All examples are placeholders and intentionally avoid
real infrastructure details.

## Goals

- Provide secure remote operational access to cluster nodes.
- Support direct SSH access to each node (`sugarkube0`..`sugarkube8`) from a remote
  operator device.
- Keep the approach reproducible for other users running their own sugarkube setup.
- Keep existing `just`-driven cluster bring-up and health workflows as the primary
  entrypoints.

## Non-goals

- Publishing secrets, auth tokens, private inventory, private domains, or real tailnet
  details.
- Replacing existing k3s bootstrap, LAN addressing, or mDNS/Avahi behavior.
- Requiring `.local` names to function across routed/remote networks.
- Rewriting cluster topology so node-to-node k3s traffic depends on Tailscale.

## Proposed topology

Each cluster node runs a local Tailscale client and joins the same tailnet as the
operator device.

```text
                     (tailnet)

   [operator-macbook]--------------------[sugarkube0]
          |------------------------------[sugarkube1]
          |------------------------------[sugarkube2]
          |------------------------------[sugarkubeN]

                (existing LAN remains unchanged)

   [sugarkube0] <----LAN + mDNS----> [sugarkube1] <----LAN----> [sugarkube2]
```

### Primary recommendation

Use **per-node tailnet membership** as the default design:

- Better failure isolation (one node's Tailscale failure does not remove access to all
  nodes).
- Direct targeting for maintenance and debugging.
- No single remote-access bottleneck.

### Optional extension

A Synology or dedicated Raspberry Pi can still be used later as a subnet router or exit
node, but that is an optional extension, not the primary recommended architecture for
this repo.

## Why per-node Tailscale

Compared with a subnet-router-only design, per-node clients improve day-two operations:

- Node-specific SSH and diagnostics are straightforward.
- Remote operations scale with node count without central choke points.
- Blast radius is smaller: losing one client does not isolate the whole cluster.

For sugarkube's operational goals, this maps better to direct node maintenance than a
single relay hop.

## Naming and discovery guidance

- `.local` and Avahi/mDNS remain useful and recommended for **local LAN bootstrap and
  discovery**.
- Remote operations should prefer Tailscale identity (for example, MagicDNS-style names)
  or explicitly configured Tailscale endpoints.
- Do not rely on `.local` names for routed remote access where multicast discovery is not
  guaranteed.

## Coexistence with existing sugarkube networking

Tailscale is **additive** in this design.

- Keep existing LAN, k3s, and Avahi/mDNS flows intact.
- Do not change node identity, addressing assumptions, or bootstrap behavior in a way that
  breaks peer communication.
- Continue to use existing sugarkube networking/bootstrap controls (`just up`, `just ha3`,
  `mdns-harden`, `mdns-selfcheck`, `node-ip-dropin`, `wlan-down`, `wlan-up`) exactly as
  documented.

Tailscale is intended for operator access (and optional control-plane reachability), not
for replacing the repo's current cluster formation topology.

## Setup flow (existing workflow first, Tailscale second)

1. Provision and bootstrap nodes with existing sugarkube flows first:
   - `just up <env>` or `just ha3 env=<env>` for bring-up.
   - `just kubeconfig`, `just status`, `just cluster-status`, and `just doctor` for
     validation and operations.
2. After each node is stable on the LAN and part of the expected cluster state, install and
   configure Tailscale on that node as a **manual step**.
3. Join the operator device to the same tailnet.
4. Validate remote SSH to each node over Tailscale identity.

> Note: this repository currently does not define a dedicated `just` helper for Tailscale
> enrollment. Keep this as an explicit manual step rather than inventing undocumented
> automation.

## Security and privacy

- Keep all docs and scripts free of secrets and private topology details.
- Use generic host inventory in examples (`sugarkube0`..`sugarkube8`) only.
- Avoid auth workflows that encourage pasting long-lived tokens into shell history.
- Apply least privilege for access policies and prefer short-lived/rotated credentials or
  expiring auth keys where available.

## Operational guidance

Generic remote SSH examples (placeholder only):

```bash
ssh <operator>@sugarkube0
ssh <operator>@sugarkube1
ssh <operator>@sugarkube2
```

Expected operational benefits:

- Faster remote triage and node-level debugging.
- Less dependency on being physically on the LAN for day-two maintenance.
- Better resilience than a single subnet-router bottleneck for remote operator reachability.

## Alternatives considered

### Dedicated Raspberry Pi subnet router

Pros:
- Centralized route advertisement can expose LAN ranges.

Cons for this repo's primary operations goal:
- Adds a single-box dependency for all remote access.
- Less direct than per-node identity when targeting individual nodes.

### Synology subnet router

Pros:
- Convenient if always-on NAS infrastructure already exists.

Cons for this repo's primary operations goal:
- Similar central bottleneck/failure domain concerns.
- Still secondary to direct per-node membership for reproducible node-by-node operations.

## Rollout / migration notes

Adopt incrementally to avoid disruption:

1. Start with one node (for example, `sugarkube0`) and confirm no regression in cluster
   behavior.
2. Validate both local and remote workflows.
3. Repeat one node at a time until all intended nodes are enrolled.
4. If regressions appear, stop rollout and keep LAN/bootstrap behavior as the source of
   truth.

## Verification checklist

- [ ] Existing cluster bring-up behavior remains unchanged (`just up`, `just ha3`).
- [ ] Existing health checks still work (`just status`, `just cluster-status`,
      `just doctor`).
- [ ] Existing LAN/mDNS workflows still work (`mdns-harden`, `mdns-selfcheck`,
      `node-ip-dropin`).
- [ ] Remote SSH works to each enrolled node over Tailscale identity.
- [ ] No sensitive values appear in docs (IPs, domains, usernames, tailnet names,
      tokens, private outputs).
