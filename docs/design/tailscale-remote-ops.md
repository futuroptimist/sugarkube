---
personas:
  - software
---

# Tailscale Remote Operations Design (Per-Node Membership)

## Overview

This design adds secure remote-operations access to Sugarkube without changing
how the cluster currently boots, discovers peers, or communicates on the local
network.

Primary recommendation: each `sugarkube<n>` node joins the same Tailscale
network individually, and operator devices (for example, a MacBook) join that
same network.

This keeps remote access reproducible for others while avoiding environment-
specific details.

## Problem statement

Sugarkube operators need a practical way to:

- securely reach cluster nodes when away from the local LAN,
- SSH to individual nodes for maintenance and debugging,
- reproduce the same pattern on their own infrastructure without relying on
  private assumptions.

## Goals

- Provide privacy-preserving remote access to each node.
- Preserve existing Sugarkube bring-up and operations workflows.
- Keep documentation public and sanitized.
- Keep rollout incremental and reversible.

## Non-goals

- Publishing secrets, tokens, usernames, IP addresses, domains, or tailnet
  names.
- Replacing existing k3s/LAN/bootstrap networking.
- Requiring `.local` hostnames to work from remote routed networks.
- Rewriting Sugarkube bootstrap logic or node identity conventions.

## Proposed topology

Each node runs a Tailscale client and authenticates as its own machine in the
same tailnet. The operator workstation also joins that tailnet.

```text
                          (Tailnet)
+-------------------+    +-------------------+
| Operator MacBook  |----|   sugarkube0      |
| (Tailscale client)|----|   sugarkube1      |
+-------------------+----|   sugarkube2 ...  |
                         |   sugarkube8      |
                         +-------------------+

Local LAN + mDNS/Avahi stay in place for cluster bootstrap and local discovery.
```

### Why per-node membership

Compared with a single subnet-router-only design, per-node membership:

- avoids a single remote-access bottleneck,
- preserves direct node-level reachability during troubleshooting,
- reduces blast radius when one gateway host is down,
- maps cleanly to common node-by-node operational tasks (SSH, log checks,
  health checks).

A dedicated subnet router (for example, separate Raspberry Pi or Synology) can
still be added later as an optional extension, but it is secondary to per-node
membership for this repository's remote-ops goals.

## Naming and discovery guidance

- Keep using `.local` and mDNS/Avahi for local LAN workflows.
- For remote operations, prefer Tailscale identity and MagicDNS-style naming
  provided by your own tailnet policy.
- Do not depend on `.local` resolving across routed/VPN boundaries.

This separation keeps local bootstrap behavior intact while making remote access
predictable.

## Coexistence with existing Sugarkube networking

Tailscale is additive. It must **not** replace or disrupt the existing:

- LAN-based k3s peer communication,
- Avahi/mDNS-based discovery and hardening,
- node-IP handling used during bootstrap,
- `just`-driven setup and operations flow.

In practice:

- keep using Sugarkube's current bootstrap process first,
- avoid changing k3s node identity assumptions solely for Tailscale,
- treat Tailscale as an operator access layer (and optional API reachability),
  not as a cluster-topology rewrite.

## Setup flow (happy path)

1. Provision each node with the existing Sugarkube flow first.
   - Use the documented cluster bring-up flow (`just up`, `just ha3`) and
     existing validation steps (`just status`, `just cluster-status`,
     `just doctor`, `just kubeconfig-env ...`) as the primary interface.
2. After a node is healthy on LAN and part of the cluster, install and
   configure Tailscale on that node as a **manual step**.
   - This repository currently documents no dedicated `just` helper for
     Tailscale enrollment.
3. Join operator devices to the same tailnet.
4. Validate remote SSH to each node individually.
5. Repeat node-by-node until all target nodes are enrolled.

> Note: This document intentionally avoids auth-token command examples to reduce
> secret leakage risk in shell history and logs.

## Security and privacy

- Never commit secrets/tokens into docs or scripts.
- Keep host inventory generic (`sugarkube0`..`sugarkube8`).
- Do not publish real tailnet names, domains, or internal addressing.
- Apply least privilege for auth and ACL policy.
- Prefer short-lived credentials/keys and periodic rotation.

## Operational guidance

Generic remote SSH pattern (placeholder only):

```bash
ssh <operator>@<node-identity-on-tailnet>
```

Expected benefits:

- safer remote maintenance access,
- faster debugging without requiring LAN presence,
- improved resilience vs. a single subnet-router chokepoint.

Failure-domain note: if one node's Tailscale client has issues, other nodes can
remain reachable when each node participates directly.

## Alternatives considered

### 1) Dedicated Raspberry Pi subnet router

Pros:

- central control point,
- can bridge broader LAN segments.

Cons:

- introduces a single-box dependency for remote access,
- weakens direct per-node operational independence.

### 2) Synology subnet router / exit-node role

Pros:

- may reuse existing always-on NAS infrastructure,
- can simplify route advertisement.

Cons:

- still centralizes remote path through one appliance,
- can drift from Sugarkube's per-node operational model.

These remain valid optional extensions, but not the primary recommendation.

## Rollout and migration notes

Adopt incrementally on existing clusters:

1. Choose one node.
2. Enroll it in Tailscale.
3. Verify normal local cluster behavior is unchanged.
4. Verify remote SSH over tailnet works.
5. Continue one node at a time.

If a node shows regressions, remove or disable its Tailscale client and return
that node to LAN-only operation while investigating.

## Verification checklist

- [ ] Existing cluster bring-up/health workflows still work (`just up`,
      `just ha3`, `just status`, `just cluster-status`, `just doctor`).
- [ ] Existing kubeconfig workflows still work (`just kubeconfig-env ...`).
- [ ] Existing local LAN/mDNS workflows still work (`.local` usage and Avahi
      behavior on the local subnet).
- [ ] Remote SSH works to each enrolled node via tailnet identity.
- [ ] No sensitive values appear in docs (IPs, domains, tailnet names,
      usernames, tokens, private command output).
