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

### 3) Continue using repo `just` commands as primary cluster interface

Use `just` recipes for cluster lifecycle and diagnostics. Use tailnet connectivity as the secure
transport path for remote operator access.


### Implementation status in this repository

The design is implemented with a dedicated helper script and `just` wrappers:

- `scripts/tailscale_remote_ops.sh` provides the operational entrypoints:
  - `install` (idempotent install path with command checks),
  - `up` (supports auth key via environment variable or file), and
  - `status` (for enrollment/state verification).
- `just tailscale-install` delegates to `scripts/tailscale_remote_ops.sh install`.
- `just tailscale-up` delegates to `scripts/tailscale_remote_ops.sh up` and forwards optional
  auth-key + extra args.
- `just tailscale-status` delegates to `scripts/tailscale_remote_ops.sh status` and forwards
  optional status args.

This keeps Tailscale-specific logic centralized in one script while preserving a simple operator UX.

### Testing and validation coverage

This feature now has both unit-level and end-to-end regression coverage:

- `tests/test_tailscale_remote_ops.py::test_tailscale_install_dry_run_reports_install_url`
  validates the install flow and dry-run behavior.
- `tests/test_tailscale_remote_ops.py::test_tailscale_up_uses_auth_key_file_and_redacts_in_dry_run`
  verifies auth-key file support and output redaction.
- `tests/test_tailscale_remote_ops.py::test_tailscale_status_recipe_e2e_with_stubs`
  exercises `just tailscale-status` end-to-end with command stubs.
- `tests/test_tailscale_remote_ops.py::test_tailscale_up_recipe_e2e_invokes_sudo_and_up`
  exercises `just tailscale-up` end-to-end with `sudo` + `tailscale` stubs.

These tests are designed to run in CI without real network enrollment while still asserting
command wiring and safety behavior.

### Troubleshooting

- If `tailscale` is already installed, `just tailscale-install` exits successfully without reinstall.
- If `sudo`, `curl`, `bash`, or `tailscale` are missing, helper commands fail fast with explicit
  error messages.
- For non-interactive testing, set `TAILSCALE_DRY_RUN=1` to print the effective commands without
  making system changes.
- To avoid shell-history leaks, prefer `TAILSCALE_AUTH_KEY_FILE` over inline key arguments whenever
  possible.

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
