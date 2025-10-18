---
title: "Stacked Pi Carrier v2 — modular 3×3 cluster with perpendicular PC fan wall"
personas:
  - hardware
  - cad
status: draft
last_updated: 2025-03-15
---

# Stacked Pi Carrier v2

This document defines the next iteration of the Sugarkube Pi carrier system: a **three-level** stack
that hosts **three Raspberry Pis per plate** (nine total) and integrates a **perpendicular fan wall**
for 120 mm PC fans (with optional 92 mm and 80 mm compatibility). The design is authored for
OpenSCAD, prints on common FDM machines with PLA, and reuses `cad/pi_cluster/pi_carrier.scad` as a
modular building block.

The goal is to produce a set of parametric SCAD modules that render to STL via the existing CAD CI
workflow, while documenting a repeatable print and assembly process.

## 1. Source layout & new files

Add the following modules under `cad/pi_cluster/`:

- `fan_patterns.scad` – helper functions for common PC-fan hole spacing and clearances.
- `fan_wall.scad` – perpendicular fan plate, insert bosses, and optional shroud lip.
- `pi_carrier_column.scad` – parametric vertical columns that align with the Pi mounting rectangle.
- `pi_carrier_stack.scad` – top-level assembly that imports `pi_carrier.scad`, generates the stack,
  and mates the fan wall to the column tabs.

Add this guide as `docs/pi_cluster_stack.md` (the file you are reading) and a user-focused assembly
companion in a follow-up change (`docs/pi_cluster_stack_assembly.md`) once prints are validated.

All new SCAD files must render cleanly through the `scripts/openscad_render.sh` pipeline that powers
GitHub Actions.

## 2. Core requirements & constraints

1. **Board geometry** – Align columns to the Raspberry Pi mounting-hole rectangle (58 mm × 49 mm)
   and maintain a safe envelope for Pi 4 and Pi 5 boards (≈85 mm × 56 mm outline) with PoE HATs.
2. **Stack height** – Default to three carriers with a configurable vertical clearance `z_gap_clear`
   that accommodates PoE HAT fans plus an intake buffer. Baseline: PoE HAT height 24 mm + 8 mm
   clearance ⇒ 32 mm gap between plates.
3. **Fan support** – Mount a 120 mm fan by default using heat-set inserts oriented perpendicular to
   the carrier planes for optimal layer strength. Expose parameters for 92 mm and 80 mm fans. Keep a
   configurable `fan_offset_from_stack` (default 15 mm) between the fan wall and columns to protect
   cabling.
4. **Printability** – Parts must fit on a 220 mm × 220 mm build plate. Orient the fan wall so layers
   run parallel to insert loads (print on its long edge). Keep minimum wall thickness ≥2.4 mm (three
   0.4 mm extrusions) anywhere threads or inserts live.
5. **Reusability** – Never duplicate the plate geometry: call the existing `pi_carrier()` module and
   respect its parameters (`standoff_mode`, `plate_thickness`, etc.).
6. **Hardware agnostic** – Support two column modes:
   - `printed`: fully printed columns with side-insert sockets for M2.5 screws that fasten into the
     carrier.
   - `brass_chain`: pass-through tubes sized for daisy-chained M2.5 brass standoffs and long screws.
7. **Documentation** – Mirror the tone and level of detail in `docs/pi_cluster_carrier.md` when
   describing tuning steps, hardware, and print settings.

## 3. Parameters (top-level `pi_carrier_stack`)

| Parameter | Default | Description |
| --- | ---: | --- |
| `levels` | 3 | Number of carrier plates. |
| `pi_per_carrier` | 3 | Fixed by `pi_carrier.scad` layout (three Pis). |
| `standoff_mode` | "heatset" | Forwarded to `pi_carrier()` to pick insert/printed/nut variants. |
| `z_gap_clear` | 32 | Vertical spacing between carrier plates (PoE HAT height + margin). |
| `poe_hat_height` | 24 | Reference HAT height; tweak to reflect vendor variation. |
| `intake_margin` | 8 | Additional free air above PoE HAT fans. |
| `column_mode` | "printed" | Column style: printed shells or brass standoff chain. |
| `column_OD` | 12 | Outside diameter of printed columns. |
| `column_wall` | 2.4 | Wall thickness of printed columns. |
| `column_corner_offset` | `[±29, ±24.5]` | XY offsets that match the Pi mounting rectangle (58×49). |
| `fan_size` | 120 | Supported fan dimensions: 120, 92, or 80 mm. |
| `fan_plate_t` | 4 | Thickness of the perpendicular fan plate. |
| `fan_offset_from_stack` | 15 | Lateral gap between columns and fan wall. |
| `fan_to_floor` | 15 | Offset from bottom plate to fan centerline. |
| `fan_insert` | `{od: 5.0, len: 4.0}` | Heat-set insert sizing for fan mount bosses (M3 hardware). |
| `carrier_insert` | `{od: 3.5, len: 4.0}` | Heat-set insert sizing for columns-to-carrier joints (M2.5). |

Expose lower-level overrides (e.g., `boss_tab_thickness`, `tab_length`) where tuning is useful, but
keep defaults within this table for clarity.

## 4. Module design notes

### 4.1 `fan_patterns.scad`

- Pure functions: `fan_hole_spacing(size)`, `fan_mount_circle(size)`, `fan_mount_hole_d(size)`.
- Return 105 mm, 82.5 mm, or 71.5 mm for 120/92/80 mm fans, respectively.
- Default hole diameter 4.5 mm for compatibility with M3–M4 hardware; actual printed holes are
  parameterized in `fan_wall.scad`.

### 4.2 `fan_wall.scad`

- Generate a rectangular plate `(fan_size + 24) × (fan_size + 24) × fan_plate_t` with a central
  circular cut-out `fan_size - 10` (leaves a 5 mm rim). Use `$fn=128` or higher for smooth edges.
- Provide two attachment systems:
  1. **Insert bosses (default)** – Side-facing cylinders sized for `fan_insert`. Bosses extend from
     the plate edge so a soldering iron can press inserts while the part lies flat.
  2. **Through holes** – Alternate mode for builders who prefer screws and nuts; include hex pockets
     on the exhaust side sized for M3 nuts.
- Add vertical rows of M3 bosses on the rear edge that align with column tabs at each level and the
  mid-span (for stiffness). Boss spacing is derived from `z_gap_clear` and `levels`.
- Include an optional shroud lip parameter (`fan_shroud_depth`, default 8 mm) to direct airflow.
- Provide helper `module fan_wall_attach(...)` to locate the plate relative to the column tabs using
  `fan_offset_from_stack` and `fan_to_floor`.

### 4.3 `pi_carrier_column.scad`

- Columns are centered on the Pi mounting holes using `column_corner_offset`.
- **Printed mode**:
  - Hollow tube: outside diameter `column_OD`, wall thickness `column_wall`, and chamfered base
    foot (1 mm × 45°) for adhesion.
  - For each `level`, add a perpendicular M2.5 insert pocket (heat-set) or printed thread cavity
    depending on `standoff_mode`. Orientation is radial so screw loads run across layers.
  - Integrate a horizontal tab (M3 clearance hole) on the outer face to accept screws from the fan
    wall bosses. Tabs should be filleted into the tube for strength.
- **Brass-chain mode**:
  - Column becomes a clearance tube for stacking brass standoffs (Ø ≈ 4.5 mm ID).
  - Add printed ledges every `z_gap_clear` with Ø2.8–3.0 mm holes for M2.5 through-bolts and
    optional hex pockets for nuts.
  - Provide bottom-foot geometry compatible with adhesive bumpers or rubber feet (15 mm diameter,
    2 mm tall suggestion).

### 4.4 `pi_carrier_stack.scad`

- `use <pi_carrier.scad>` to access the existing module without duplication.
- Instantiate four columns at the Pi mounting-hole corners.
- Loop `levels` times, translating `pi_carrier()` by `i * z_gap_clear` along Z.
- Call `fan_wall_attach(...)` on the outer columns (e.g., positive X side) to position the fan wall.
- Include optional `explode` parameter that spaces components apart for inspection renders.
- Echo key dimensions for CI logs: `levels`, `fan_size`, `column_mode`, and spacing.

## 5. Print guidance

- **Material** – PLA or PETG. PLA is acceptable if the stack is kept below ~40 °C ambient; PETG is
  more tolerant near PoE HATs.
- **Layer height** – 0.2 mm. Increase to 0.28 mm for draft prints, but keep perimeters at 4 and
  infill ≥30 % gyroid.
- **Fan wall orientation** – Print on its long edge with supports under the rim if needed. This
  aligns filament strands with the perpendicular screws and prevents delamination around the bosses.
- **Columns** – Print upright with concentric top/bottom surfaces. Add a 0.4 mm horizontal pause at
  insert pockets to minimize stringing before heat-set installation.
- **Carrier plates** – Continue printing as described in `docs/pi_cluster_carrier.md`; this design
  does not modify the base plate geometry.

## 6. Hardware bill of materials (per 3×3 stack)

| Item | Quantity | Notes |
| --- | ---: | --- |
| Raspberry Pi 4/5 | 9 | With PoE or PoE+ HATs if power-over-Ethernet is needed. |
| PoE HAT | 9 | Ensure height ≤ `poe_hat_height` or adjust parameter. |
| M2.5 heat-set inserts | 36 | Four per Pi carrier corner across three levels. |
| M2.5 × 22 mm screws | 36 | Carrier mounting screws (compatible with current build). |
| M2.5 brass spacers (11 mm) | 36 | Between Pi boards and carriers. |
| M3 heat-set inserts | 12 | Four for the fan, remainder for fan-wall mounting bosses. |
| M3 × 12 mm screws | 4 | Fan to fan-wall attachment. |
| M3 × 8 mm screws | 8 | Fan wall to column tabs. |
| 120 mm PC fan | 1 | PWM recommended; substitute 92 mm or 80 mm by parameter. |
| Rubber feet (optional) | 4 | 12–15 mm diameter stick-on pads. |

Adjust counts if `levels` differs from 3.

## 7. Assembly sequence (high level)

1. Print three carrier plates (one per level) using the preferred `standoff_mode`.
2. Print four columns and the fan wall in the chosen mode.
3. Install M2.5 heat-set inserts into carrier plates and column pockets while parts are still warm.
4. Install M3 inserts into the fan wall bosses.
5. Bolt each Raspberry Pi (with PoE HAT) to a carrier using M2.5 screws and brass spacers.
6. Fasten carriers to the columns starting from the bottom, checking alignment of the mounting holes
   at each level.
7. Attach the fan wall to the column tabs with M3 screws, ensuring the fan intake faces the Pi stack.
8. Mount the 120 mm fan to the wall using M3 screws and route cables through the fan-to-stack gap.
9. Optionally add rubber feet or fix the base to a panel using the column feet.

## 8. Verification & acceptance

- **CAD validation** – `openscad` renders succeed for both `column_mode` options and for fan sizes
  120, 92, and 80 mm. CI artifacts include STL previews for each combination.
- **Dimensional checks** – Measure column spacing to confirm 58 mm × 49 mm centers. Fan wall hole
  spacing matches the selected fan within ±0.2 mm.
- **Print fit** – Columns slide over inserts without cracking; fan screws engage fully without
  stripping layers.
- **Thermal test** – With a 120 mm fan at ~1 000 RPM, PoE HAT intake temperatures stay below 60 °C in
  a 25 °C room.

## 9. Future extensions

- Add optional rear cable management clips that snap to column tabs.
- Provide parametric cut-outs for HDMI/USB harnesses if carriers are reoriented.
- Explore a detachable PSU bracket that shares the column attachment points.

---

Implementers should follow `docs/prompts/codex/implement.md` when converting this specification into
code. Update this document with real-world photos and assembly notes once the prototype is printed.
