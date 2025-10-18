---
personas:
  - hardware
  - cad
status: draft
last_updated: 2025-10-18
---

# Stacked Pi Carrier v2 — modular 3×3 cluster with perpendicular fan wall

This design brief defines the next iteration of the Raspberry Pi carrier system inside the
`cad/pi_cluster/` tree. The goal is to build on the existing
[`pi_carrier.scad`](../cad/pi_cluster/pi_carrier.scad) triple-board plate and deliver a modular
assembly that holds **three carriers vertically** (nine Raspberry Pis total) while adding a
**perpendicular 120 mm PC-fan wall** for cross-flow cooling. Every part must be printable on a
standard FDM printer using PLA and follow the repository’s OpenSCAD/CI conventions.

The document is written so future `implement.md` prompts can translate it directly into code,
STL renders, and user-facing documentation.

---

## 1. Objectives

1. Reuse `pi_carrier.scad` as an imported module; do not duplicate the base geometry.
2. Stack three carriers (default) using aligned vertical columns that pick up the Raspberry Pi
   58 mm × 49 mm mounting-hole rectangle.
3. Provide two column strategies: fully printed columns with heat-set inserts, or clear tubes for
   daisy-chained brass standoffs.
4. Add a perpendicular fan plate that supports 80/92/120 mm fans, defaulting to 120 mm, mounted via
   M3 heat-set inserts oriented perpendicular to the carrier planes.
5. Keep the design parametric so users can alter stack height, fan size, and hardware choices.
6. Ensure all parts print cleanly in PLA on 220 mm × 220 mm (or larger) beds. The fan wall should be
   printable on its side to keep fastener loads across layers.

---

## 2. Mechanical constraints & references

- **Raspberry Pi footprint:** Board outline ≈ 85 mm × 56 mm with M2.5 mounting holes on a 58 mm ×
  49 mm rectangle (Ø ≈ 2.7 mm). Match the existing constants in `pi_carrier.scad`.
- **PoE HAT clearance:** Assume PoE/PoE+ hats with integrated 25 mm fans and total heights up to
  ~24 mm. Add an 8 mm intake buffer so the external fan does not obstruct airflow.
- **Fan standards:** Support 80 mm (71.5 mm hole pitch), 92 mm (82.5 mm pitch), and 120 mm
  (105 mm pitch) axial fans. Through-holes should default to Ø3.2 mm for M3 clearance.
- **Fasteners & inserts:** Reuse the defaults from `pi_carrier.scad` for M2.5 heat-set inserts on the
  carriers. New M3 insert bosses for the fan wall should target a 5.0 mm OD × 4.0 mm length insert
  with ~0.2 mm interference.

---

## 3. File layout additions

Add the following OpenSCAD modules under `cad/pi_cluster/`:

| File | Purpose |
| ---- | ------- |
| `fan_patterns.scad` | Helper functions for translating fan sizes to hole spacings and fastener diameters. |
| `fan_wall.scad` | Perpendicular plate with fan cut-out, insert bosses, and mounting interface to columns. |
| `pi_carrier_column.scad` | Parametric vertical column aligned to Pi mounting holes; supports printed and brass-chain modes. |
| `pi_carrier_stack.scad` | Top-level assembly that instantiates carriers, columns, and the fan wall. |

Documentation:

- `docs/pi_cluster_stacked_carrier.md` (this file) – keep in sync with implementation.
- Update or cross-link `docs/pi_cluster_carrier.md` once the new stack is available (follow-up task).

Rendering & CI:

- The existing `scripts/openscad_render.sh` should pick up new `.scad` files; ensure they render in
  both `heatset` and `printed` modes when applicable.
- Add optional `echo()` statements summarizing key parameters for CI logs.

---

## 4. Top-level parameters (defaults)

All dimensions are in **millimetres** unless noted.

| Parameter | Default | Description |
| --------- | ------: | ----------- |
| `levels` | 3 | Number of carrier plates in the stack. |
| `pi_per_carrier` | 3 | Derived from `pi_carrier.scad` – do not change in the stack module. |
| `standoff_mode` | "heatset" | Passed directly to `pi_carrier()` for existing insert/through/nut behaviour. |
| `z_gap_clear` | 32 | Vertical spacing between carrier plates (`poe_hat_height + intake_margin`). |
| `poe_hat_height` | 24 | Expected maximum height of a PoE HAT including top fan. |
| `intake_margin` | 8 | Free space above PoE HAT fan intake. Additive to `poe_hat_height`. |
| `column_mode` | "printed" | "printed" uses PLA columns with side-loaded inserts; "brass_chain" accepts brass standoffs. |
| `column_od` | 12 | Outside diameter of printed column shells. |
| `column_wall` | 2.4 | Wall thickness (≥3 × 0.4 mm nozzle width). |
| `column_pitch_x` | 58 | X spacing between column centres (matches Pi holes). |
| `column_pitch_y` | 49 | Y spacing between column centres (matches Pi holes). |
| `fan_size` | 120 | Supported: 80, 92, 120. |
| `fan_plate_thickness` | 4 | Thickness of fan wall plate. |
| `fan_offset_from_stack` | 15 | Gap between outer column face and fan wall interior. |
| `fan_center_offset_z` | 15 | Offset from bottom carrier plane to fan centre to align with stack mid-line. |
| `fan_insert` | `{od: 5.0, length: 4.0}` | Heat-set insert geometry for fan mount bosses (M3). |
| `carrier_insert` | `{od: 3.5, length: 4.0}` | Heat-set insert geometry reused from carrier (M2.5). |

Expose these as OpenSCAD `module` parameters to keep the stack configurable. Derived values such as
`stack_height = levels * plate_thickness + (levels - 1) * z_gap_clear` can be computed internally.

---

## 5. Module design details

### 5.1 `fan_patterns.scad`

- Provide simple pure functions, e.g. `fan_hole_spacing(size)` returning 105/82.5/71.5.
- Optional helpers:
  - `fan_mount_diameter(size)` – recommended Ø3.2 for M3 screws.
  - `fan_cutout_diameter(size)` – default to `size - 10` to leave a 5 mm rim.
- Keep the file dependency-free so it can be reused elsewhere.

### 5.2 `fan_wall.scad`

- Import `fan_patterns.scad`.
- Create a rectangular plate sized `(fan_size + 24) × (fan_size + 24)` to leave a consistent 12 mm
  rim around the fan. Thickness defaults to `fan_plate_thickness`.
- Cut a centred circular opening with diameter `fan_cutout_diameter(fan_size)`.
- Place four fan mounting holes/bosses at the corners of the square pitch returned by
  `fan_hole_spacing(fan_size)`.
  - **Boss strategy (default):** Create side-access cylinders sized for the M3 insert so the part can
    be printed on its side. Orient bosses so heat-set inserts are pressed along the print layers,
    not against them. Add thin ribs tying each boss back into the plate.
  - **Through-hole option:** Provide a boolean parameter to skip bosses and create Ø3.2 holes with
    hex recesses for captive M3 nuts on the exhaust side.
- Along the rear edge (facing the carrier stack), create mounting bosses at each column interface:
  - Two vertical rows aligned with the right-side columns (matching `column_pitch_y`).
  - For a three-level default, place bosses at `z = 0`, `z = z_gap_clear`, `z = 2*z_gap_clear`, and
    optional mid-span bosses for rigidity.
  - Bosses accept M3 heat-set inserts; tabs on the columns carry matching clearance holes.
- Include chamfered cable pass-through slots near the top/bottom if needed to route fan power wires
  back toward the carrier stack.

### 5.3 `pi_carrier_column.scad`

- Position four columns at the Pi mounting-hole rectangle corners (`±column_pitch_x/2`,
  `±column_pitch_y/2`) relative to the carrier’s centroid.
- **Printed mode:**
  - Use a hollow cylinder with `column_od` outer diameter and `column_od - 2*column_wall` inner
    diameter.
  - At each level height, add a transverse hole/boss for an M2.5 heat-set insert. Inserts should be
    installed from the column exterior so screws pass through tabs on the carrier plate and engage
    the column.
  - Provide a small flat or key to prevent columns from rotating when tightening screws.
- **Brass-chain mode:**
  - Replace side insert pockets with vertical clearance for stacked female–female brass standoffs.
  - Add shelves or collars at each level with Ø2.8–3.0 pass-through holes to register the standoffs.
  - Optionally include hex pockets to trap M2.5 nuts.
- Bottom features:
  - Integrate foot pads or allow `foot_height` parameter for optional bumpers.
  - Provide counterbores for rubber feet if desired.
- Top features:
  - Optional cap or handle to lift the stack.
- Expose helper modules: `column(levels=3, mode="printed")` and `column_tab(z_index)` returning the
  geometry for connecting to the fan wall.

### 5.4 `pi_carrier_stack.scad`

- `use <pi_carrier.scad>` to import the existing module.
- Include the new modules and orchestrate the assembly:

  ```scad
  use <pi_carrier.scad>
  include <fan_patterns.scad>
  include <fan_wall.scad>
  include <pi_carrier_column.scad>

  module pi_carrier_stack(levels=3, z_gap_clear=32, fan_size=120, column_mode="printed") {
      columns(levels, z_gap_clear, column_mode);
      for (i = [0:levels-1])
          translate([0, 0, i * z_gap_clear])
              pi_carrier(standoff_mode=standoff_mode);
      fan_wall_attach(fan_size, levels, z_gap_clear);
  }
  ```

- Align carrier origin with stack origin so columns and fan wall tabs line up with the Pi standoffs.
- Provide helper modules for individual sub-assemblies (e.g. `carrier_level(i)` and
  `fan_wall_attach()`) to simplify testing and CI renders.
- Export default preview by calling `pi_carrier_stack();` at the end of the file, following the
  existing pattern.

---

## 6. Print and assembly guidance

- **Material:** PLA or PETG; PLA is sufficient for indoor use. Aim for 0.2 mm layers, ≥4 perimeters,
  and 30–40 % gyroid infill on structural parts.
- **Carrier plates:** Print flat as before. Use brass inserts if available for durability.
- **Columns:** Print upright; enable 0.6 mm minimum external wall thickness. For printed columns,
  orient the part so transverse insert pockets bridge cleanly (may require small support tabs).
- **Fan wall:** Print on its long edge so M3 bosses are oriented along the layer lines. If necessary,
  add sacrificial brims for stability.
- **Heat-set inserts:** Target hole diameters 0.2 mm undersized relative to insert OD (e.g. 3.3 mm for
  a 3.5 mm insert) to match the existing carrier tolerances.

Assembly overview:

1. Install M2.5 heat-set inserts into each carrier and column connection point.
2. Screw carriers to columns, starting from the bottom, using M2.5 × 8 (printed mode) or the chosen
   brass standoff hardware (brass-chain mode).
3. Mount Raspberry Pis and PoE HATs using the existing BOM (M2.5 × 22 screws with 11 mm standoffs).
4. Attach the fan wall to column tabs with M3 × 8 screws. Leave a 15 mm gap to route cables.
5. Install the PC fan using M3 × 12 screws and captive nuts or inserts. Orient airflow across the
   PoE HAT fans to avoid recirculation.

---

## 7. Hardware bill of materials (per 3-level stack)

| Quantity | Part | Notes |
| --------:| ---- | ----- |
| 36 | M2.5 × 22 mm pan-head screws | Pi mounting (3 per Pi, plus spares). |
| 12 | M2.5 × 11 mm brass standoffs | Between Pi and carrier (reuse from current design). |
| 36 | M2.5 heat-set inserts, Ø3.5 mm × 4 mm | For carrier standoffs if using heat-set mode. |
| 12 | M2.5 × 8 mm screws | Carrier-to-column joints (printed column mode). |
| 8 | M3 heat-set inserts, Ø5 mm × 4 mm | Four for fan, four for wall-to-column bosses. |
| 4 | M3 × 12 mm screws + washers | Fan mounting. |
| 4 | M3 × 8 mm screws | Fan wall to columns. |
| 1 | 120 mm PC fan (Noctua/Arctic, etc.) | Default size; ensure 105 mm hole spacing. |

Adjust quantities if `levels` or fan size changes. For brass-chain column mode, swap the M2.5 × 8
screws for stacked female–female standoffs and long through-bolts.

---

## 8. Acceptance criteria

- New `.scad` files compile without warnings and render into STL artifacts via the existing CI.
- `pi_carrier_stack.scad` produces at least six STL variants in CI: column modes (printed, brass) ×
  fan sizes (80, 92, 120).
- Column centres align with the Raspberry Pi mounting-hole rectangle so carriers bolt in without
  shims.
- Fan wall hole spacing matches the chosen fan size within ±0.2 mm.
- Assembled stack clears PoE HAT fans with `poe_hat_height=24` and `intake_margin=8`.
- Entire assembly fits within 220 mm × 220 mm × 220 mm print volume when split into components.
- Documentation updated (this file and follow-up additions) so builders can reproduce the stack.

---

## 9. Implementation checklist

1. Create the new OpenSCAD modules and wire them together in `pi_carrier_stack.scad`.
2. Add parameterised rendering targets to the CI configuration if needed.
3. Generate preview renders locally (`openscad` or `scripts/openscad_render.sh`).
4. Update docs (this file, plus cross-links). Include photos or diagrams once hardware is built.
5. Validate fit with a physical prototype; record any required tolerance tweaks.

---

## 10. Future enhancements

- Optional cable-management clips along columns for PoE/Ethernet routing.
- Snap-on shroud for the fan wall to improve airflow direction or support filters.
- Swappable base plate with integrated DIN-rail hooks or wall-mount features.
- Sensor mounting bosses for temperature telemetry.

