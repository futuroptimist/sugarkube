# Tailscale Remote Operations Design (Public, Reproducible)

## Overview

This design describes a privacy-preserving way to operate a sugarkube cluster remotely without
changing the cluster's existing LAN/bootstrap behavior.

The primary goal is to let an operator device (for example, a MacBook) securely reach each
`sugarkube<n>` node for SSH and day-two operations over Tailscale.

Tailscale is additive in this design. Existing cluster formation and health workflows (for
example `just up`, `just ha3`, `just doctor`, `just status`, and `just cluster-status`) stay as-is.

## Problem statement

We need a reproducible remote-operations topology that allows:

- secure access from an operator laptop when away from the LAN,
- direct SSH access to each node (`sugarkube0` ... `sugarkube8`), and
- public documentation that does not leak private infrastructure details.

## Goals and non-goals

### Goals

- Provide secure remote operator access to each node.
- Keep node-level access independent and resilient.
- Preserve existing sugarkube/k3s setup, bootstrap, and local troubleshooting flows.
- Keep guidance reproducible for readers running their own tailnet and LAN.

### Non-goals

- Publishing secrets, auth tokens, user inventories, or private network identifiers.
- Documenting real IP addresses, usernames, host inventory, or real tailnet names.
- Replacing existing LAN, Avahi/mDNS discovery, or k3s peer networking.
- Requiring `.local` hostname resolution to work over routed remote links.

## Proposed topology

Primary recommendation: each node joins the same tailnet individually.

```text
                    (tailnet)

  Operator laptop  <---- encrypted mesh ---->  sugarkube0
      (MacBook)                                 sugarkube1
                                                sugarkube2
                                                ...
                                                sugarkube8

  Existing LAN remains in place for cluster bootstrap, k3s peer traffic,
  Avahi/mDNS discovery, and local `.local` workflows.
```

Key properties:

- Every `sugarkube<n>` node runs a Tailscale client.
- The operator device also runs a Tailscale client in the same tailnet.
- Remote access targets nodes directly instead of transiting a single gateway.
- A dedicated subnet router (for example a Synology or separate Pi) is optional future extension,
  not the primary design.

## Why per-node Tailscale membership

Per-node membership is preferred because it:

- avoids a single subnet-router bottleneck/failure domain,
- allows independent node troubleshooting (SSH each node directly),
- makes rollout incremental (one node at a time), and
- keeps the operational model aligned with node-by-node cluster maintenance.

A subnet router can still be useful for additional routed resources later, but sugarkube remote
ops should not depend on that single box for basic node access.

## Naming and discovery guidance (`.local` vs remote)

- On the local LAN, `.local` and Avahi/mDNS are still useful and should continue to work.
- For remote operations, prefer Tailscale identity naming (for example, MagicDNS-style node names)
  rather than relying on `.local` across routed boundaries.
- Keep documentation generic: use placeholders and node patterns such as `sugarkube0` to
  `sugarkube8`.

## Coexistence with existing sugarkube networking

This design must **not** alter the existing cluster networking assumptions.

- Keep existing bring-up/bootstrap behavior unchanged (`just up`, `just ha3`).
- Keep existing LAN-based discovery and mDNS hardening workflows unchanged (for example,
  `mdns-harden`, `mdns-selfcheck`, and the Avahi/node-IP scripts already used by bring-up).
- Do not change node identity in ways that disrupt k3s peer communication.
- Treat Tailscale as an operator access plane (and optional control-plane reachability aid),
  not as a rewrite of cluster topology.

## Suggested setup flow

1. Provision each node with the existing sugarkube flow first:

   - `just up <env>` for normal bootstrap, or
   - `just ha3 env=<env>` for the 3-server HA flow.

2. Verify cluster health with existing commands:

   - `just status`
   - `just cluster-status`
   - `just doctor`

3. Install and configure Tailscale manually on each node.

   This repository does not currently provide a dedicated `just` helper for Tailscale setup.
   Keep these steps manual and provider-documented rather than inventing new automation here.

4. Join the operator device to the same tailnet.

5. Validate remote SSH access to each node using generic host placeholders.

## Operational guidance (generic examples)

Use generic SSH patterns only (no real usernames, no private domain details), for example:

```bash
ssh <operator-user>@<tailscale-node-identity>
```

Expected benefits:

- remote maintenance without exposing LAN services directly,
- direct access for logs/debugging on specific nodes, and
- less operational coupling than a single subnet-router-only architecture.

## Security and privacy

- Do not commit auth keys, auth URLs, or bootstrap tokens.
- Do not publish real tailnet names, internal domains, or private addresses.
- Avoid command examples that encourage pasting long-lived credentials into shell history.
- Apply least privilege for node access policies.
- Prefer expiring/rotated credentials and short-lived auth where supported.

## Alternatives considered

### Dedicated Raspberry Pi subnet router

Pros:

- one place to manage routed subnet advertisement.

Cons:

- creates a single operational chokepoint for access to all nodes,
- adds failure coupling and extra maintenance burden.

### Synology subnet router

Pros:

- convenient if always-on NAS infrastructure already exists.

Cons:

- still centralizes access through one device,
- portability/reproducibility depends on optional external hardware.

These alternatives are valid extensions, but secondary to direct per-node membership for
sugarkube's remote-ops goals.

## Rollout and migration notes

Adopt incrementally to avoid disruption:

1. Start with one node.
2. Confirm k3s and LAN workflows remain healthy.
3. Confirm remote SSH over Tailscale for that node.
4. Repeat node-by-node until all desired nodes are enrolled.

If any node rollout causes unexpected behavior, remove or disable Tailscale on that node and
re-validate with the existing `just` health commands before proceeding.

## Verification checklist

- [ ] Existing cluster behavior still works (`just up`/`just ha3` flows unchanged).
- [ ] `just status`, `just cluster-status`, and `just doctor` still report expected health.
- [ ] SSH over Tailscale works for each enrolled `sugarkube<n>` node.
- [ ] Local LAN/mDNS workflows still work for `.local` use on the local network.
- [ ] No secrets or private environment values appear in docs.
