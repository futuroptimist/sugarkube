---
title: "Sugarkube: Homelab-to-Federation Roadmap (Vision)"
status: vision
owners:
  - futuroptimist
last_updated: 2025-10-18
audience:
  - contributors
  - homelab builders
  - future operators
summary: >
  A multi-year plan to evolve Sugarkube from a single indoor Raspberry Pi cluster into a
  resilient, multi-cluster, optionally federated platform that others can replicate and
  extend. The end state is a small, open, sovereign compute fabric that can interconnect
  with the wider Fediverse.
---

## Why this exists

Sugarkube pairs open hardware with open software so individuals can **self-host** durable
services at home and in the field. The roadmap below captures the long-term direction:
start with a compact 3×3 Raspberry Pi stack for dev/integration/prod, add a solar-powered
off-grid cluster for continuity, then add a third **remote** site for stronger availability.
Over time, we align with **Fediverse** patterns so others can operate compatible nodes and
(optionally) interconnect.

This document is aspirational. It is **not** a sprint plan and is intentionally
implementation-agnostic where details are still in motion.

---

## Guiding principles

- **Open & permissive.** Hardware designs and software are published under permissive
  licenses so anyone can replicate, modify, and run their own stacks.
- **Edge-first Kubernetes.** Use **k3s** for simplicity, ARM friendliness, and low overhead
  on single-board computers (SBCs); it is a CNCF-backed, fully compliant Kubernetes
  distribution designed for resource-constrained and edge environments.
- **Zero inbound ports.** Expose services via **Cloudflare Tunnel** (`cloudflared`), which
  provides egress-only connectivity plus DNS and load-balancing options.
- **Separation of concerns.** Maintain distinct tiers for **prod**, **integration**, and
  **dev/ephemeral**, each independently upgradable.
- **Multi-cluster as a capability, not a dependency.** Start single-site; add multi-cluster
  service connectivity and/or federation when useful (e.g., Cilium Cluster Mesh, Submariner,
  or KubeFed).
- **Portable overlays.** Use modern VPN tech (e.g., **WireGuard**) for site-to-site or
  node-to-node overlays when required.
- **Federation with social protocols (stretch).** Where it makes sense (status beacons,
  presence, activity streams), prefer open protocols such as **ActivityPub** to interoperate
  with the broader Fediverse.

---

## End-state at a glance

- **Region A (Indoor / Primary):** 3×3 Raspberry Pi 5 stack on the *stacked pi_carrier*
  with a 120 mm fan wall. Three logical tiers (prod, integration, dev).
- **Region B (Off-grid / Continuity):** Aluminum-extrusion frame with PV + MPPT + battery,
  LTE backhaul, hardened enclosure; runs a self-contained k3s cluster and exports telemetry.
- **Region C (Remote / HA):** Low-cost remote site (e.g., Midwest) with its own backhaul;
  participates in cross-cluster service connectivity and/or replication.
- **Control plane choices:**
  - Cross-cluster **service connectivity** via Cilium **Cluster Mesh** or **Submariner**
    (DNS service discovery via Lighthouse).
  - **Resource propagation/federation** via **KubeFed** (Template/Placement/Overrides)
    where a single host cluster coordinates configuration across member clusters.
- **Ingress:** Egress-only publishing through Cloudflare Tunnel from each region, with DNS
  or load-balancer steering.
- **Overlay:** Optional WireGuard peering for site-to-site secure transport.
- **Social/fed interop (optional):** ActivityPub-compatible status feeds for cluster
  presence or notifications.

---

## Phased roadmap

### Phase N — Indoor 3×3 (today → near-term)
A compact nine-node Raspberry Pi 5 cluster arranged as three carriers × three boards each.

**Objectives**
- Reliable **dev → integration → prod** promotion within the same chassis.
- Egress-only publishing via Cloudflare Tunnel; per-tier hostnames and Zero Trust policies.
- GitOps for cluster/app config; observability baseline (Prometheus, Grafana, Loki).
- Repeatable imaging and health checks (automated *spot-check* style routines).

**Kubernetes layer**
- k3s for small footprint, ARM optimization, and reduced operational surface area.

**Result**
- A self-contained lab that can ship real services with production safety in a home setting.

---

### Phase N+1 — Off-grid continuity cluster (solar + LTE)
A fieldable, weather-resistant single cluster powered by PV + battery, with LTE backhaul.
Designed to operate autonomously for long periods.

**Objectives**
- Survive ISP or power outages at Region A.
- Export battery and solar telemetry to Region A for proactive maintenance.
- When WAN is available, sync artifacts and data; when isolated, continue serving core apps
  locally.

**Networking**
- Prefer egress-only publishing via Cloudflare Tunnel; add WireGuard peering for inter-site
  overlays as needed.

**Result**
- True business continuity for homelab workloads: power-sovereign and network-resilient.

---

### Phase N+2 — Remote micro-datacenter (geo redundancy)
A third site physically distant from Regions A and B to absorb regional disasters and
enable geographic redundancy.

**Objectives**
- Replicate critical services across regions.
- Optional multi-cluster **service connectivity** (Cilium Cluster Mesh or Submariner) for
  east-west traffic and name resolution; or **federation** (KubeFed) for policy/config
  propagation.
- Policy-driven placement of workloads; deliberate failure domains.

**Notes**
- KubeFed’s Template/Placement/Overrides model allows selective propagation without
  mandating a single vendor stack.

---

## Architecture building blocks

### Kubernetes distribution
- **k3s** (server/agent model) with ARM-optimized packaging and minimal dependencies,
  suitable for SBCs and edge deployments.

### Cross-cluster choices
- **Service connectivity path**
  - **Cilium Cluster Mesh:** L3/L4 datapath extension across clusters; full policy
    enforcement and global services. Requires consistent CNI (Cilium) and non-overlapping
    PodCIDRs, typically with basic inter-cluster IP reachability or VPN.
  - **Submariner (plus Lighthouse):** CNI-agnostic L3 interconnect with encrypted tunnels
    and multi-cluster service discovery via DNS; supports broker-based control and
    overlapping CIDRs via Globalnet.
- **Federation path**
  - **KubeFed:** Host cluster coordinates resource propagation using federated CRDs
    (Template/Placement/Overrides). Useful for consistent configuration and policy across
    regions.

> Either path can be used alone or combined: for example, Submariner for connectivity plus
> KubeFed for policy propagation.

### Ingress & publishing
- **Cloudflare Tunnel** (`cloudflared`) from each region to publish services without
  opening inbound firewall ports; DNS or load-balancer rules steer per-region endpoints.

### Site overlays
- **WireGuard** for low-overhead, modern Layer 3 tunnels when direct IP reachability is
  needed between regions.

---

## Fediverse alignment (optional but encouraged)

Sugarkube should be easy to fork and **federate socially**. Over time we can ship a small
sidecar or controller that emits or consumes **ActivityPub** objects for:

- **Presence** (cluster or node up/down, service heartbeat)
- **Events** (deploys, alerts, advisories)
- **Discovery** (operator contact, public endpoints)

ActivityPub is a **W3C Recommendation** that uses ActivityStreams 2.0 JSON for interoperable
messages; adopting it allows third-party instances—including other homelabs—to follow and
react to Sugarkube events in the wider Fediverse.

---

## Environments & naming (indoor 3×3)

Suggested logical mapping for the initial stack:

- **Tier A — prod** (two nodes for high availability plus one maintenance spare)
- **Tier B — integration**
- **Tier C — dev/ephemeral agents**

DNS or hostnames can reflect tiering; each tier runs its own Cloudflare Tunnel route:

```
prod.example.tld        -> cloudflared (Region A, Tier A)
int.example.tld         -> cloudflared (Region A, Tier B)
dev.example.tld         -> cloudflared (Region A, Tier C)
continuity.example.tld  -> cloudflared (Region B)
remote.example.tld      -> cloudflared (Region C)
```

### Security & operations (baseline)

- Zero-trust ingress: identity-aware rules on Cloudflare; no inbound ports on sites.
- Overlay keys: rotate WireGuard keys on schedule; keep peer lists minimal.
- Secrets: encrypted-at-rest GitOps (e.g., SOPS with age) and node-local least privilege.
- Observability: metrics, logs, and traces per region; cross-region rollups when WAN is up.

---

## Risks & mitigations

- **Multi-cluster complexity.** Cilium Cluster Mesh, Submariner, and KubeFed introduce new
  failure modes. Start single-site and add capabilities gradually. Read the upstream docs to
  understand constraints (CNI requirements, CIDR overlaps, broker or host-member roles).
- **Backhaul fragility.** LTE or satellite links can be jittery; design services to degrade
  gracefully and favor pull-based synchronization.
- **Power budget drift.** Validate solar sizing margins and log battery state to plan
  maintenance windows.

---

## What this document is / is not

- **Is:** A durable, long-term direction for Sugarkube and a template others can adapt.
- **Is not:** A near-term implementation plan. Specific SCAD, wiring, and Kubernetes
  manifests live elsewhere and will evolve.

---

## References

- k3s — <https://docs.k3s.io>
- Cloudflare Tunnel — <https://github.com/cloudflare/cloudflared>
- Cilium Cluster Mesh — <https://docs.cilium.io/en/stable/network/clustermesh/>
- Submariner (plus Lighthouse) — <https://submariner.io>
- KubeFed — <https://github.com/kubernetes-sigs/kubefed>
- WireGuard — <https://www.wireguard.com>
- ActivityPub — <https://www.w3.org/TR/activitypub/>
