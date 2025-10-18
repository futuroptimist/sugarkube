---
personas:
  - hardware
  - cad
status: draft
---

# Stacked Pi Carrier v2 — 3×3 cluster with perpendicular fan wall

This design extends the existing triple-Pi carrier at `cad/pi_cluster/pi_carrier.scad` into a
stackable nine-node cluster cooled by a perpendicular 120 mm PC fan (92 mm and 80 mm are optional
variants). The assembly keeps `pi_carrier.scad` as the base plate module for each level, adds
vertical columns aligned with the Raspberry Pi mounting pattern, and introduces a removable fan wall
printed on its side for strength.

The intent is to produce modular OpenSCAD components that integrate with the current repository
layout, generate STL artifacts through the existing CI pipeline, and remain printable on common FDM
printers using PLA.

## System layout

* **Carriers:** Three Raspberry Pi boards per carrier, reusing `pi_carrier.scad` without geometry
  changes so all previously documented standoff modes remain available.
* **Stack:** Three carriers separated by configurable vertical spacing to clear PoE HATs and cable
  runs.
* **Columns:** Four vertical posts coincident with the Raspberry Pi hole rectangle (58 mm × 49 mm).
  Posts accept either printed heat-set inserts or daisy-chained brass standoffs.
* **Fan wall:** A detachable plate that mounts a standard PC fan perpendicular to the stack.
  Heat-set insert bosses are oriented sideways so the part can be printed lying flat.
* **Bed footprint:** The base carrier footprint stays within the dimensions already validated for the
  triple carrier, while the fan wall panel fits diagonally on a 220 mm bed when printed separately.

## File additions

```
cad/pi_cluster/
  fan_patterns.scad       // shared hole spacing helpers (80/92/120 mm)
  fan_wall.scad           // perpendicular plate with insert bosses and airflow window
  pi_carrier_column.scad  // vertical posts with tabs or brass-standoff guides
  pi_carrier_stack.scad   // top-level stack assembly that reuses pi_carrier()
docs/
  pi_cluster_stack.md     // this design document (assembly + BOM guidance)
```

Each `.scad` file should render cleanly through `scripts/openscad_render.sh`, which the CI workflow
already calls for CAD changes.

## Top-level parameters

| Parameter | Default | Description |
| --- | ---: | --- |
| `levels` | 3 | Number of carriers in the stack (3×3 = 9 Pis by default). |
| `standoff_mode` | "heatset" | Passed directly into `pi_carrier()` so printed/nut variants remain available. |
| `z_gap_clear` | 32 | Vertical spacing between carrier plates (`poe_hat_height + intake_margin`). |
| `poe_hat_height` | 24 | Expected PoE/PoE+ HAT height budget (tune per accessory). |
| `intake_margin` | 8 | Extra clearance to avoid blocking on-board PoE fans. |
| `column_mode` | "printed" | `"printed"` for PLA posts with heat-set pockets, `"brass_chain"` for hollow guides that accept brass spacers. |
| `column_od` | 12 | Outside diameter of the printed column shell. |
| `column_wall` | 2.4 | Wall thickness (≥3 perimeters with a 0.4 mm nozzle). |
| `column_pitch_x` | 58 | X spacing between column centers (matches Pi hole pattern). |
| `column_pitch_y` | 49 | Y spacing between column centers (matches Pi hole pattern). |
| `fan_size` | 120 | Supported fan sizes: 120, 92, or 80. |
| `fan_plate_thickness` | 4 | Wall thickness for the perpendicular plate. |
| `fan_offset_from_stack` | 15 | Air gap between outer column face and fan wall interior. |
| `fan_center_z_offset` | 15 | Offset from bottom carrier surface to fan centerline. |
| `fan_insert` | `{od: 5.0, length: 4.0}` | Heat-set insert sizing for M3 fan screws. |
| `carrier_insert` | `{od: 3.5, length: 4.0}` | Heat-set insert sizing for M2.5 column fasteners (matches existing carrier spec). |

All dimensions are in millimeters. Parameters should be surfaced through `pi_carrier_stack.scad`
with sensible defaults and allow overrides via `-D` flags for CI renders.

## Module responsibilities

### `fan_patterns.scad`

* Provide pure functions that map a fan size (80/92/120) to a bolt-circle spacing (71.5/82.5/105)
  and recommended hole diameters (3.2 mm through-hole, 4.5 mm counterbore).
* No dependencies. Keep the file small so other modules can `use` it without pulling geometry.

### `pi_carrier_column.scad`

* Emit a single column positioned at one corner of the Pi mounting rectangle.
* For `column_mode="printed"` create:
  * Hollow cylinder with the specified OD and wall thickness.
  * Side-facing heat-set insert pockets at every carrier level (`z = level * z_gap_clear`).
    Sideways pockets align with the printed layer stack for strength.
  * Optional mid-span ribs to resist torsion when tightening screws.
* For `column_mode="brass_chain"` create:
  * Clearance bore sized for M2.5 female–female brass standoffs.
  * Horizontal shelves with through-holes so long screws can pass and clamp the carriers.
  * Hex pockets to trap nuts if users prefer through-bolts instead of inserts.
* Add foot pads or a printable base to prevent rocking when the stack sits on a bench.

### `fan_wall.scad`

* Generate a rectangular plate sized to the selected fan with a central circular cutout.
* Include four fan mounting bosses with sideways heat-set pockets sized for M3 inserts. Bosses should
  be printable without supports when the wall is laid on its side.
* Along the edge that meets the stack, create vertical rails or tabs with M3 inserts at each carrier
  level plus the midpoint between top and bottom for stiffness.
* Add optional shroud lip (parameterized) to guide airflow across the Pis; default to 0 for a flat
  wall but leave the option exposed for future tuning.

### `pi_carrier_stack.scad`

* `use <pi_carrier.scad>` to access the existing carrier module instead of duplicating geometry.
* Arrange carriers with `translate([0, 0, level * z_gap_clear]) pi_carrier(standoff_mode=...)`.
* Instantiate four columns at the coordinates defined by the Pi mounting pattern, plus mirror or
  translate as needed to align with the carrier origin.
* Attach the fan wall to the right-hand side (positive X) columns using tabs that match the insert
  pattern produced in `fan_wall.scad`. Respect `fan_offset_from_stack` when positioning.
* Echo summary dimensions (`levels`, `fan_size`, `column_mode`) to help with CI log inspection.

## Hardware bill of materials (per 3-level stack)

| Item | Quantity | Notes |
| --- | ---: | --- |
| Raspberry Pi with PoE HAT | 9 | Pi 5 or Pi 4 footprint supported by `pi_carrier.scad`. |
| M2.5 × 22 mm screws | 12 | One per Pi corner when using heat-set inserts in the carrier standoffs. |
| M2.5 × 11 mm brass spacers | 12 | Matches existing single-carrier build guide; extend as needed for top accessories. |
| Heat-set inserts, M2.5 × 4 mm | 12 | Optional if relying on the carrier’s `heatset` variant. |
| Heat-set inserts, M3 × 4 mm | 8 | Four for the fan, four for the wall-to-column interface (add two extras for mid-span bosses). |
| M3 × 12 mm screws | 4 | Fan to wall (adjust length for guard or grill). |
| M3 × 8 mm screws | 6 | Wall to column tabs (two per carrier level). |
| M2.5 × 8 mm screws | 12 | Column tabs into carriers when using printed column mode. |
| Optional rubber feet | 4 | Stick-on bumpers under the base carrier.

Hardware counts assume the default three-level stack; adjust proportionally if `levels` changes.

## Printing guidance

* **Material:** PLA or PETG. If ambient temperature exceeds 35 °C prefer PETG to avoid creep.
* **Layer height:** 0.2 mm; **perimeters:** ≥4; **infill:** 30–40 % gyroid or cubic.
* **Carriers:** Print flat as before. Reuse existing standoff drilling instructions from the Pi
  carrier field guide.
* **Columns:** Print upright with 0.6 mm minimum external wall width. Enable support for the
  sideways insert pockets if needed, or chamfer the pockets so supports are unnecessary.
* **Fan wall:** Lay the part on its long edge so the insert bosses are printed horizontally and can
  withstand screw clamp loads. Add a brim to prevent warping.
* **Post-processing:** Install heat-set inserts using a soldering iron with depth stop. Allow parts to
  cool fully before final assembly.

## Assembly sequence

1. Print three carrier plates (or reuse existing stock) and install M2.5 inserts per the chosen
   `standoff_mode`.
2. Print four columns and verify that the insert pockets align with carrier thickness. Press-fit or
   install M2.5 inserts depending on `column_mode`.
3. Mount the bottom carrier to the columns using M2.5 × 8 mm screws or brass spacers.
4. Add the middle and top carriers, ensuring PoE HAT fans face the upcoming airflow.
5. Print the fan wall, install M3 inserts, and bolt a 120 mm fan using M3 × 12 mm screws (use
   92 mm/80 mm fans by changing the parameter before rendering).
6. Attach the fan wall to the column tabs with M3 × 8 mm screws, leaving the configurable
   `fan_offset_from_stack` gap for cable clearance.
7. Route Ethernet and power cables, then secure the assembly to a base or rack as desired.

## Validation checklist

* OpenSCAD renders succeed for all combinations exercised by CI:
  * Column modes: `printed`, `brass_chain`.
  * Fan sizes: 80 mm, 92 mm, 120 mm.
* Column XY positions line up with the Raspberry Pi mounting rectangle (58 mm × 49 mm) within
  ±0.2 mm when measured from the exported STL.
* Default `z_gap_clear` of 32 mm provides at least 8 mm overhead clearance above a 24 mm PoE HAT.
* Fan wall bolt-circle spacing matches the selected fan within ±0.2 mm.
* All components fit on printers with 220 mm × 220 mm beds when printed as oriented above.
* Assembled stack maintains stability (no rocking) on flat surface; add optional base plate if extra
  rigidity is required.

## Implementation notes

* Reuse constants from `pi_carrier.scad` where possible (hole spacing, board dimensions) by exposing
  helper functions or shared include files to avoid drift.
* Keep module interfaces parametric so future clusters can adopt more or fewer levels without
  rewriting geometry.
* Consider adding an optional cable management channel along the fan wall for PoE leads.
* Echo computed widths/heights in `pi_carrier_stack.scad` to simplify debugging in CI logs.
* Update `docs/pi_cluster_carrier.md` later if user-facing assembly instructions need to reference
  the stacked configuration.

