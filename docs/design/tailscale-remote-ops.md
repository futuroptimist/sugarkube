---
personas:
  - software
---

# Tailscale Remote Operations Design (Public, Reproducible)

## Overview

This design adds **remote operator access** to `sugarkube` without changing the existing cluster
bootstrap and LAN behavior. The recommended topology is:

- each `sugarkube<n>` node joins the same tailnet individually, and
- each operator workstation (for example, a MacBook) also joins that tailnet.

Tailscale is treated as an additive management plane for remote operations, not a replacement for
existing k3s/LAN/bootstrap networking.

## Problem statement

`sugarkube` needs a practical way to:

- securely access cluster nodes from outside the local network,
- SSH to individual nodes directly for maintenance and debugging, and
- keep the approach reproducible for others using this repository.

## Goals

- Enable remote SSH and operator access to each node.
- Preserve existing `just`-based bring-up and day-two workflows.
- Keep docs safe for public sharing (sanitized examples only).

## Non-goals

- Publishing secrets, auth keys, tailnet identifiers, or private inventory.
- Replacing k3s peer networking or LAN bootstrap with an overlay-only topology.
- Requiring `.local` names to work over routed/WAN paths.
- Modifying existing Avahi/mDNS, node IP drop-ins, or cluster bootstrap logic.

## Proposed topology

Primary recommendation:

1. Provision nodes with the existing `sugarkube` flow.
2. Install a Tailscale client on each `sugarkube<n>` node.
3. Join all nodes and operator devices to the same tailnet.
4. Perform remote operations by targeting nodes directly over tailnet identity.

```text
                 Remote network / internet

         +----------------------------------------+
         | Operator device (e.g. MacBook)         |
         | tailnet member                         |
         +-------------------+--------------------+
                             |
                        (tailnet mesh)
                             |
     --------------------------------------------------------------
      |                |                |                 |
+-----+------+   +-----+------+   +-----+------+    +-----+------+
| sugarkube0 |   | sugarkube1 |   | sugarkube2 |    | sugarkubeN |
| tailscale  |   | tailscale  |   | tailscale  |    | tailscale  |
+-----+------+   +-----+------+   +-----+------+    +-----+------+
      |                |                |                 |
      +----------------+----------------+-----------------+
                       Existing LAN + k3s cluster networking
```

Optional extensions (secondary):

- A dedicated Raspberry Pi subnet router.
- A Synology subnet router and/or exit node.

Those can be useful in some environments, but they are not the primary recommendation for this
repo's remote-operations goals.

## Why per-node Tailscale membership

Per-node membership avoids a single-network-appliance bottleneck for day-to-day operations:

- direct reachability to each node,
- fewer dependencies on one subnet-router host,
- clearer failure isolation (one node can fail without removing access to all others), and
- easier, incremental rollout one node at a time.

## Naming and discovery guidance

- **Local LAN workflows:** `.local`/mDNS remains useful on the same broadcast domain for discovery
  and first-hop setup.
- **Remote workflows:** prefer Tailscale identity naming (for example, MagicDNS-style names) instead
  of relying on `.local` across routed boundaries.

Use placeholders in docs and scripts (for example, `sugarkube0`, `sugarkube1`, or generic
MagicDNS-style names) and avoid publishing private naming details.

## Coexistence with existing sugarkube networking

This design must coexist with current repository behavior:

- keep existing LAN/bootstrap entry points (`just up`, `just ha3`) unchanged,
- keep existing kubeconfig flows (`just kubeconfig`, `just kubeconfig-env`) unchanged,
- keep operational checks (`just doctor`, `just status`, `just cluster-status`) unchanged,
- keep Avahi/mDNS and node-IP helpers (`mdns-harden`, `mdns-selfcheck`, `node-ip-dropin`,
  `wlan-down`, `wlan-up`) unchanged.

Tailscale should not alter node identity or addressing in a way that breaks k3s peer communication,
bootstrap behavior, or LAN discovery already used by `sugarkube`.

## Setup flow (happy path)

### 1) Bring up cluster with existing repo flow first

Follow the existing setup sequence first (for example, `just up <env>` or `just ha3 env=<env>`),
then validate with `just status` and `just cluster-status`.

### 2) Add Tailscale on each node as a post-provisioning step

This repository now includes helper recipes for the node-local Tailscale setup flow:

- `just tailscale-install` installs the upstream Tailscale package.
- `just tailscale-up` brings the node online with your local auth flow.
- `just tailscale-status` verifies enrollment state.

Example (placeholder-only) usage:

```bash
just tailscale-install
just tailscale-up
just tailscale-status
```

Optional remote SSH probe:

```bash
just tailscale-ssh-check target='<operator>@sugarkube0'
```

### 3) Continue using repo `just` commands as primary cluster interface

Use `just` recipes for cluster lifecycle and diagnostics. Use tailnet connectivity as the secure
transport path for remote operator access.

## Security and privacy considerations

- Never commit auth keys, tokens, or private tailnet metadata.
- Keep inventory generic in public docs (`sugarkube0`..`sugarkube8` only).
- Avoid command examples that encourage token pasting into shell history.
- Apply least-privilege access controls for operators.
- Prefer short-lived credentials, key expiry, and routine credential rotation.

## Operational guidance

Generic SSH examples (placeholder-only):

```bash
ssh <operator>@sugarkube0
ssh <operator>@sugarkube1
```

Expected benefits:

- faster remote troubleshooting,
- safer maintenance without exposing cluster services publicly,
- simpler per-node debugging and log collection.

Failure-domain note: direct per-node membership avoids making a single subnet-router host the only
path to all nodes.

## Alternatives considered

### Dedicated Raspberry Pi subnet router

- **Pros:** centralized routing for LAN subnets.
- **Cons:** introduces a single operational choke point for remote access.

### Synology subnet router

- **Pros:** may fit existing homelab storage/network stacks.
- **Cons:** still centralizes access on one appliance; node-level reachability depends on it.

For this repository's remote-operations goals, per-node membership remains the preferred baseline.

## Rollout and migration notes

Adopt incrementally to avoid disruption:

1. Choose one existing node.
2. Install/join Tailscale for that node.
3. Validate remote SSH and normal cluster behavior.
4. Repeat for the next node.

Do not rewire existing cluster networking during rollout.

## Verification checklist

- [ ] Existing cluster bring-up/ops flows still work (`just up`, `just ha3`, `just doctor`,
      `just status`, `just cluster-status`).
- [ ] SSH to each enrolled node works over the tailnet.
- [ ] Local LAN/mDNS workflows still work as before.
- [ ] No private values are present in docs (IPs, domains, tailnet names, usernames, tokens,
      copied private outputs).

## Implementation status in this repository

The Tailscale remote-operations design is now implemented with dedicated automation in:

- `scripts/tailscale_remote_ops.sh` for install/up/status/SSH probes.
- `just tailscale-install`
- `just tailscale-up`
- `just tailscale-status`
- `just tailscale-ssh-check`

The automation is designed to be safe for public repos:

- auth keys are supplied through environment variables, not hard-coded values.
- status checks require a healthy `BackendState=Running`.
- SSH verification is explicit and opt-in per host.

## Operator quick reference

Use this sequence on each `sugarkube<n>` node after base cluster setup:

```bash
# 1) Install Tailscale
just tailscale-install

# 2) Bring node online (interactive auth)
just tailscale-up

# 3) Verify node health in tailnet
just tailscale-status

# 4) (From operator workstation) validate SSH path
just tailscale-ssh-check target='<operator>@sugarkube0'
```

If you use an ephemeral auth key, provide it only at runtime and avoid shell history capture:

```bash
read -r -s TS_AUTH_KEY
just tailscale-up auth_key="$TS_AUTH_KEY"
unset TS_AUTH_KEY
```

## Failure modes and remediation

### `tailscale-status` reports backend not running

1. Check service state: `sudo systemctl status tailscaled`.
2. Restart service if needed: `sudo systemctl restart tailscaled`.
3. Re-run `just tailscale-status`.

### `tailscale-up` succeeds but remote SSH fails

1. Confirm target uses tailnet identity (`<operator>@sugarkube<n>`).
2. Confirm node-level SSH policy in your ACLs.
3. Run `just tailscale-ssh-check target='<operator>@sugarkube<n>'` for an explicit probe.
