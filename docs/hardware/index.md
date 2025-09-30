---
personas:
  - hardware
---

# Sugarkube Hardware Index

Use this page to jump straight to the physical build resources, safety notes,
and maintenance routines that keep the enclosure healthy. Cross-link the guides
you touch in PRs so hardware and documentation stay in sync.

## Shared Fundamentals
- [Sugarkube Fundamentals](../fundamentals/index.md) — review background primers
  once before diving into persona-specific hardware checklists.

## Safety and Planning
- [SAFETY.md](../SAFETY.md) — wiring, battery handling, and workbench checklists.
- [power_system_design.md](../power_system_design.md) — plan panel, charge controller,
  and battery sizing.

## Build Guides and Fixtures
- [build_guide.md](../build_guide.md) — step-by-step frame assembly and wiring.
- [pi_cluster_carrier.md](../pi_cluster_carrier.md) — Raspberry Pi carrier plate.
- [lcd_mount.md](../lcd_mount.md) — optional 1602 LCD placement.
- [mac_mini_station.md](../mac_mini_station.md) — keyboard station for the lab bench.
- [insert_basics.md](../insert_basics.md) — heat-set insert techniques used across
  the enclosure.

## Field References and Playbooks
- [Pi Carrier Field Guide](../pi_carrier_field_guide.md) — printable one-page
  checklist for on-site work.
- [pi_carrier_launch_playbook.md](../pi_carrier_launch_playbook.md) — full
  walkthrough from inventory to powered-on cluster.
- [pi_boot_troubleshooting.md](../pi_boot_troubleshooting.md) — LED cues and
  triage steps when the hardware refuses to boot.

## Storage and Power Maintenance
- [ssd_post_clone_validation.md](../ssd_post_clone_validation.md) — confirm SSD
  migrations succeed before decommissioning the SD card.
- [ssd_health_monitor.md](../ssd_health_monitor.md) — schedule SMART snapshots to
  catch failing drives early.
- [docs/tutorials/tutorial-06-raspberry-pi-hardware-power.md](../tutorials/tutorial-06-raspberry-pi-hardware-power.md)
  — hands-on exercises for validating solar and battery wiring.
