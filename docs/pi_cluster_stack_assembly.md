---
personas:
  - hardware
  - cad
status: published
last_updated: 2025-11-12
---

# Stacked Pi Carrier Assembly Guide

Use this walkthrough when turning the `cad/pi_cluster/` modules into a working
nine-node Raspberry Pi cluster with the perpendicular fan wall. Pair it with the
design specification in [pi_cluster_stack.md](pi_cluster_stack.md) for exact
clearances, tuning parameters, and CAD references.

## Bill of materials

| Item | Qty | Notes |
| --- | ---: | --- |
| `pi_carrier.scad` plates | 3 | Print the variant matching your fasteners (heatset/through/nut). |
| Columns (`pi_carrier_stack`) | 4 | Four columns; works with printed or brass-chain builds. |
| Fan wall | 1 | Printed `fan_wall` module sized to the selected `fan_size`. |
| Raspberry Pi 5 boards | 9 | Populate three Pis per level. |
| M2.5 × 22 mm screws | 12 | Tie each carrier to the column stack. |
| M2.5 heat-set inserts (3.5 mm OD × 4 mm) | 12 | Install when using the printed-column mode. |
| Brass spacers, M2.5 female–female, 11 mm | 12 | Maintain clearance between the Pi and carrier. |
| PC fan (80/92/120 mm) | 1 | Match the fan size to the `fan_size` parameter. |
| M3 × 16 mm screws | 4 | Secure the fan to the wall bosses. |
| M3 heat-set inserts (5 mm OD × 4 mm) | 4 | Seat in the fan wall before final assembly. |
| Cable ties or hook-and-loop straps | 6 | Optional strain relief for power/Ethernet harnesses. |

## Tooling and consumables

- Adjustable temperature soldering iron or heat-set insert tip for M2.5/M3
  inserts.
- 2.0 mm and 2.5 mm hex drivers (or Phillips #0 if using pan-head screws).
- Flush cutters for trimming support material and cable ties.
- Calipers for verifying insert depth and fan alignment.
- Blue painter's tape or cardboard to protect the work surface while pressing
  inserts.
- Isopropyl alcohol and lint-free wipes to clean mating surfaces after printing.

## Preflight checks

1. Confirm all STL files rendered successfully via the automation (see
   `scripts/render_pi_cluster_variants.py`) or regenerate locally with
   `openscad` before committing to a print.
2. Inspect prints for stringing on the column pockets and remove any wisps so
   inserts seat flush.
3. Dry-fit one column to a carrier to ensure the M2.5 hardware aligns with the
   58 mm × 49 mm hole rectangle. Reprint if alignment error exceeds 0.2 mm.
4. Verify the fan wall bosses accept the selected M3 inserts without cracking.

## Assembly checklist

1. **Prep the carriers.** Follow the insert installation guidance in
   [pi_cluster_carrier.md](pi_cluster_carrier.md) and seat the brass spacers so
   each plate is ready for a Pi board.
2. **Populate the columns.** Heat and press the M2.5 inserts into the column
   pockets (or assemble the brass standoff chains) starting from the bottom
   level. Let the plastic cool before stacking additional tiers.
3. **Stack the carriers.** Start with the lowest carrier, align the columns, and
   fasten with M2.5 × 22 mm screws. Repeat for the remaining two tiers, keeping
   the cable cut-outs aligned down the rear spine.
4. **Mount the fan wall.** Slide the wall tabs over the column bosses, insert
   the shared M2.5 screws, and secure the PC fan using the prepared M3 hardware.
   Aim airflow toward the Pis so the PoE HAT fans receive fresh intake.
5. **Cable management.** Route Ethernet and power along the back of the columns
   with cable ties or hook-and-loop straps. Leave slack for maintenance and SSD
   swaps.

## Post-assembly validation

- Power each Pi in sequence and monitor idle temperatures; PoE HAT sensors
  should stabilise below 60 °C with the fan wall operating.
- Run `sugarkube pi smoke --dry-run` to confirm the automation helpers remain in
  place before heading on-site.
- Record clear photos of the finished stack and update your lab notebook or
  evidence repository. Future contributors rely on these references to spot
  regressions.

Regression coverage: `tests/test_pi_cluster_stack_assembly_doc.py` ensures this
guide, the hardware index link, and the design-spec deliverable remain in sync.
