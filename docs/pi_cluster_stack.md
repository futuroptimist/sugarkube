---
title: "Stacked Pi Carrier v2 — modular 3×3 cluster with perpendicular PC-fan wall"
slug: "pi-cluster-stacked-carrier"
personas:
  - hardware
  - cad
owners:
  - futuroptimist
status: draft
last_updated: 2025-02-13
---

# Stacked Pi Carrier v2

This document specifies a stackable Raspberry Pi carrier system that reuses the existing
`cad/pi_cluster/pi_carrier.scad` module as a building block and adds:

1. **Vertical stacking** of carriers (three Raspberry Pis per carrier, three carriers tall by
   default).
2. A **perpendicular fan wall** that accepts standard PC fans (80/92/120 mm) via heat-set inserts
   oriented perpendicular to the carrier plates.
3. Print-friendly geometry for **FDM/PLA**, with all parts printable on common beds.

The design integrates with this repository’s OpenSCAD layout and documentation workflow. It is
intended to be implemented as new `.scad` modules under `cad/pi_cluster/` and companion
documentation under `docs/`. The base triple-Pi carrier already exists as
`cad/pi_cluster/pi_carrier.scad`; we import and reuse it rather than reimplementing its details.

---

## 1. Context and constraints

- **Boards & holes.** Raspberry Pi 5/4 outline ≈ 85 mm × 56 mm with M2.5 mounting holes on a
  58 mm × 49 mm rectangle (Ø ≈ 2.7 mm). Use these dimensions for column placement and clearances.
- **PoE HAT clearance.** Official PoE/PoE+ HATs include a 25 mm fan and top-side components; do not
  obstruct the intake. Default vertical spacing should assume *HAT height + intake margin*.
- **Fan standards.** Support the following center-to-center mounting hole patterns out of the box:
  - 120 mm fan → 105 mm × 105 mm pattern (e.g., Noctua NF-A12x25).
  - 92 mm fan → 82.5 mm × 82.5 mm pattern (e.g., Arctic F9).
  - 80 mm fan → 71.5 mm × 71.5 mm pattern (common guards and filters).
- **Repository interfaces.**
  - Reuse `pi_carrier.scad` (triple-Pi base with `standoff_mode` variants: `heatset`, `through`,
    `nut`) and its parameters (`corner_radius`, `gap_between_boards`, etc.).
  - Keep documentation consistent with `docs/pi_cluster_carrier.md` tone and structure.
  - Follow `docs/prompts/codex/implement.md` when turning this spec into code so new parts pass CI
    and STL rendering.

---

## 2. Files to add

```
cad/pi_cluster/
  fan_patterns.scad        # fan hole spacing helpers (80/92/120)
  fan_wall.scad            # perpendicular fan plate + insert bosses
  pi_carrier_column.scad   # vertical columns (printed or brass-chain)
  pi_carrier_stack.scad    # top-level assembly (stack + fan wall)
docs/
  pi_cluster_stack.md      # this design + future assembly/BOM guide
```

The CI already renders all `.scad` files into `stl/` via `scripts/openscad_render.sh`. Existing
regression tests under `tests/cad_regress_test.py` automatically pick up new modules.

---

## 3. Parameters (top level)

All dimensions are in millimetres unless otherwise noted.

| Parameter | Default | Purpose |
| --- | ---: | --- |
| `levels` | 3 | Number of carriers stacked vertically. |
| `pi_per_carrier` | 3 | Fixed by the existing `pi_carrier.scad` layout (three Pis). |
| `standoff_mode` | `"heatset"` | Forwarded to `pi_carrier.scad` for board standoffs. |
| `z_gap_clear` | 32 | Vertical gap between carrier plates; typically `poe_hat_height + intake_margin`. |
| `poe_hat_height` | 24 | Expected PoE(+)/aftermarket HAT height; adjustable for vendor variation. |
| `intake_margin` | 8 | Extra clearance above the HAT fan intake to avoid recirculation. |
| `column_mode` | `"printed"` | `"printed"` = printed columns with heat-set inserts each level;<br>`"brass_chain"` = daisy-chained brass standoffs aligned to Pi holes. |
| `column_OD` | 12 | Column outside diameter. |
| `column_wall` | 2.4 | Column wall thickness (≥ three extrusion widths at 0.4 mm nozzle). |
| `column_pitch` | `58 × 49` | Column XY spacing matching the Pi hole rectangle for alignment. |
| `fan_size` | 120 | Supported values: 80, 92, 120. |
| `fan_plate_t` | 4 | Thickness of the perpendicular fan plate. |
| `fan_offset_from_stack` | 15 | Gap from the outermost column to the fan wall (cable clearance). |
| `fan_to_floor` | 15 | Z-offset from the bottom carrier to the fan hole centre (centres airflow). |
| `fan_insert` | `{od: 5.0, L: 4.0}` | M3 heat-set insert geometry for the fan wall bosses. |
| `carrier_insert` | `{od: 3.5, L: 4.0}` | M2.5 heat-set insert geometry for Pi columns (matches current defaults). |

Notes:

- `poe_hat_height` uses a conservative default; published HAT heights range from the high teens to
  ~24 mm, so keep it user-tunable.
- Board geometry/hole spacing comes from the Raspberry Pi mechanical drawings; treat the
  58 mm × 49 mm rectangle as invariant.

---

## 4. Module design

### 4.1 `fan_patterns.scad`

Provide dependency-free helpers for fan hole spacing and drill sizes:

```scad
function fan_hole_spacing(size) =
    size == 120 ? 105 :
    size == 92  ? 82.5 :
    size == 80  ? 71.5 : 105; // default to 120 mm pattern

function fan_hole_circle_d(size) = 4.5; // M4/#6 pass-through (oversize for M3 screws)
```

Values are derived from common PC fan datasheets (Noctua NF-A12x25, Arctic F9, 80 mm guards). Add an
optional helper for square patterns if future fans require it.

### 4.2 `fan_wall.scad`

The fan wall is a separate part printed on its side so the screw loads act across layers.

Goals:

- Accept 80/92/120 mm fans.
- Orient heat-set inserts perpendicular to the carrier planes.
- Provide optional shroud lip (10–15 mm) to direct airflow across the Pis.

Geometry:

- Rectangular plate: `(fan_size + 2 * 12) × (fan_size + 2 * 12) × fan_plate_t`.
- Central circular cut-out: `fan_size - 10` diameter to maintain a consistent rim.
- Mount holes: square layout at `fan_hole_spacing(fan_size)`, Ø3.2–3.4 mm through holes.
  - **Boss option (default):** 6.5 mm OD × `fan_insert.L + 0.6` boss protruding from the side so
    inserts are installed with the part laying flat. Reinforce bosses with ribs.
  - **Through-hole option:** Ø3.2 mm with hex pockets for captive M3 nuts on the exhaust side.
- Wall-to-column interface: two vertical rows of M3 insert bosses along the rear edge spaced per
  carrier level (`z = 0`, `z_gap_clear`, `2 * z_gap_clear`) plus mid-span bosses for stiffness. These
  mate with tabs on the right-side columns via M3×8 screws.

### 4.3 `pi_carrier_column.scad`

Four columns align with the Pi mounting hole rectangle and carry loads through the stack.

- **Printed mode (`column_mode = "printed"`):** Hollow cylinders (`column_OD`, `column_wall`). At each
  level add a cross-bored pocket for an M2.5 heat-set insert oriented radially so plate screws pull
  across layers.
- **Brass-chain mode (`column_mode = "brass_chain"`):** Provide a clearance tube for daisy-chained
  M2.5 female–female brass standoffs with shelves every `z_gap_clear` featuring Ø2.8–3.0 mm
  pass-through holes and optional hex pockets to trap nuts during assembly.
- **Base anchoring:** Integrate non-rocking foot pads or provide a separate `feet.scad` for bumpers.

### 4.4 `pi_carrier_stack.scad`

Top-level assembly that imports existing modules and composes the stack:

```scad
use <pi_carrier.scad>
use <fan_patterns.scad>
include <pi_carrier_column.scad>
include <fan_wall.scad>

module pi_carrier_level(z = 0) {
  translate([0, 0, z]) pi_carrier();
}

module pi_carrier_stack(levels = 3, z_gap_clear = 32, fan_size = 120) {
  columns(levels, z_gap_clear);
  for (i = [0 : levels - 1])
    pi_carrier_level(i * z_gap_clear);
  fan_wall_attach(fan_size, levels, z_gap_clear);
}

pi_carrier_stack();
```

- **Columns:** Place four instances at the Pi hole rectangle corners. Tabs on the right-side columns
  expose M3 holes for the fan wall.
- **Fan wall:** Attach using `fan_offset_from_stack` to set the lateral gap. Provide parameters for
  shroud depth and mounting orientation.
- **Echo diagnostics:** Emit key parameters (`levels`, `fan_size`, `column_mode`) to simplify CI logs.

---

## 5. Print guidance (FDM/PLA)

- Material: PLA (or PETG if ambient temperature exceeds 35 °C).
- Layer height: 0.2 mm. Perimeters: ≥4. Infill: 30–40 % gyroid.
- **Fan wall:** Print on its side so insert bosses and mount ears carry load across layers.
- **Columns:** Print upright; ensure ≥0.6 mm external walls for stronger threads. Enable ironing or
  support blockers as needed for insert pockets.
- **Carrier plates:** Continue printing via existing `pi_carrier.scad` defaults.
- Heat-set inserts: For M2.5 inserts with 3.5 mm OD × 4 mm length, size pockets with ~0.2 mm
  interference (hole ≈ 3.3 mm). Match current carrier defaults for consistency.

---

## 6. Hardware (per 3×3 stack)

- **Per Raspberry Pi (×9):** M2.5 × 22 pan-head screw + M2.5 11 mm brass spacer (aligns with existing
  documentation; adjust for washers if needed).
- **Columns & carriers:**
  - Printed columns → M2.5 × 8 screws inserted sideways into each carrier (four corners × levels).
  - Brass-chain columns → M2.5 female–female standoffs stacked to `z_gap_clear` height plus long
    through-screws and nuts.
- **Fan wall:**
  - M3 heat-set inserts (four for the fan, six to eight for wall-to-column tabs).
  - M3 × 12 screws for mounting the fan, M3 × 8 for securing the wall to column tabs.

---

## 7. Thermal intent & placement

- Orient the fan to blow across PoE-HAT intakes without creating recirculation; maintain at least
  8–10 mm clearance from obstructions (enforced via `intake_margin`).
- Prefer 120 mm fans for best CFM/dBA; 92 mm and 80 mm remain options for tighter envelopes.
- Consider adding cable guides or clips on the columns to keep wiring clear of the fan path.

---

## 8. Acceptance criteria

**CAD & CI**

- New SCAD files compile locally and via CI to STL artifacts without OpenSCAD warnings.
- `pi_carrier_stack.scad` renders three STL variants (columns: `printed`, `brass_chain`; fan sizes:
  80/92/120).

**Geometry checks**

- Column XY centres align with the 58 mm × 49 mm Pi hole rectangle; carriers bolt in without shims.
- Fan wall hole pattern matches `fan_hole_spacing(fan_size)` within ±0.2 mm.

**Print & assembly**

- All parts fit on a 220 mm × 220 mm bed (Prusa class) or 256 mm × 256 mm bed (Bambu A1).
- Heat-set inserts seat flush without layer splitting.
- With `poe_hat_height = 24` and `intake_margin = 8`, the fan wall clears cables and PoE-HAT fans.

**Operational**

- With a 120 mm fan at ~900–1200 RPM, expect idle CPU temperatures ≤58–60 °C for Pi 5 units with PoE
  HATs in warm rooms (validate empirically).

---

## 9. Implementation notes

- Reuse the base: call `pi_carrier()` directly from `pi_carrier_stack.scad`, passing through
  `standoff_mode`.
- Columns should expose tab spacing as parameters so the fan wall can adjust without geometry edits.
- Default printed-hole clearances: Ø3.2 mm for M3, Ø2.8 mm for M2.5; heat-set pockets undersized by
  0.2 mm relative to insert OD.
- Add minimal `echo()` summaries to assist CI diagnostics.
- Create and maintain an assembly/BOM guide below once the design is implemented.

---

## Assembly guide

Follow these steps to turn printed or machined parts into a working stack. The walkthrough mirrors
the cadence of [`docs/pi_cluster_carrier.md`](./pi_cluster_carrier.md) so returning contributors can
reuse their muscle memory (regression coverage: `tests/test_pi_cluster_stack_doc.py`).

### Prepare the carriers

1. Print three copies of `pi_carrier.scad` using `standoff_mode = "heatset"` unless brass hardware is
   preferred.
2. Dry-fit Raspberry Pis and PoE HATs to confirm clearances before committing inserts.
3. Install M2.5 heat-set inserts from the underside of each carrier, checking that the bosses stay
   perpendicular so the columns register cleanly.
4. Flash the latest Sugarkube image to storage with `sugarkube pi flash --device /dev/sdX` and place
   the cards aside for final assembly.

### Install the columns

1. Print the four column variants required for your build (`column_mode = "printed"`) or stage the
   brass standoff chain if using `"brass_chain"` mode.
2. Starting at the base carrier, anchor each column with M2.5 × 8 screws and confirm that inserts
   seat flush.
3. Stack the remaining carriers, securing each level before moving on to the next. Verify that
   wiring channels align and leave enough clearance for PoE HAT cables.
4. Route USB-C or barrel power leads along the columns, using zip ties or clips to keep them clear of
   the future fan wall airflow.

### Mount the fan wall

1. Print `fan_wall.scad` with the correct `fan_size` parameter. Pause after the first 1–2 mm to press
   M3 inserts if your printer supports insert pauses, or heat-set them manually once the plate
   cools.
2. Attach the fan to the wall using M3 × 12 screws. Confirm that wires exit toward the carrier stack
   for tidy strain relief.
3. Position the wall so the fan pulls across the PoE HAT intakes, then secure it to the columns with
   M3 × 8 screws.
4. Install flashed storage, boot each Pi, and run `sugarkube pi smoke` to validate networking and PoE
   budgets before placing the stack into service.

---

## Bill of materials

| Quantity | Item | Notes |
| ---: | --- | --- |
| 9 | Raspberry Pi 5 (or 4) | One per carrier slot; PoE HAT recommended |
| 9 | PoE or PoE+ HAT | Height informs `poe_hat_height` parameter |
| 9 | microSD or NVMe storage | Flash via `sugarkube pi flash` prior to assembly |
| 36 | M2.5 heat-set inserts | Four per Pi × nine positions |
| 36 | M2.5 × 8 screws | Carrier-to-column hardware |
| 12 | Columns | Printed columns or brass standoff chains |
| 1 | 80/92/120 mm fan | Select size to match thermal target |
| 4 | M3 heat-set inserts | Fan wall bosses |
| 4 | M3 × 12 screws | Fan to wall |
| 4 | M3 × 8 screws | Fan wall to columns |
| 4 | Zip ties or cable clips | Keep wiring clear of airflow |

Add power distribution, PoE switches, and mounting trays according to your deployment environment.

---

## 10. OpenSCAD pseudocode (key pieces)

```scad
// fan_patterns.scad
function fan_hole_spacing(sz) =
    sz == 120 ? 105 :
    sz == 92  ? 82.5 :
    71.5; // default to 80 mm spacing if unspecified

// fan_wall.scad
module fan_wall(sz = 120, t = 4, boss = true) {
  hs = fan_hole_spacing(sz);
  difference() {
    cube([sz + 24, sz + 24, t], center = true);
    cylinder(h = t + 0.4, r = (sz - 10) / 2, $fn = 128);
  }
  for (x = [-hs/2, hs/2])
    for (y = [-hs/2, hs/2])
      translate([x, y, 0]) {
        if (boss)
          rotate([0, 90, 0]) cylinder(h = 6.5, r = (5.0 - 0.2) / 2, $fn = 40);
        drill_m3_through();
      }
  // rear-edge bosses for column mounts (spacing derived from z_gap_clear)
}

// pi_carrier_column.scad
module column(levels = 3, zgap = 32, mode = "printed") {
  // place at one corner of the 58 × 49 mm rectangle
  // add side pockets (heat-set) or pass-through shelves per mode
}

// pi_carrier_stack.scad
use <pi_carrier.scad>
include <fan_wall.scad>
include <pi_carrier_column.scad>

module pi_carrier_stack(levels = 3, zgap = 32, fan_size = 120) {
  columns(levels, zgap);
  for (i = [0 : levels - 1])
    translate([0, 0, i * zgap]) pi_carrier();
  fan_wall_attach(fan_size, levels, zgap);
}
```

---

## 11. Safety and references

- Do not block PoE HAT fans; maintain airflow clearance.
- Use official Raspberry Pi mechanical drawings for board geometry when modifying clearances.
- Fan hole spacings: 120 mm → 105 mm, 92 mm → 82.5 mm, 80 mm → 71.5 mm; consult manufacturer
  datasheets if supporting additional sizes.

---

## 12. Deliverables checklist (for future implementation)

- [ ] Add `fan_patterns.scad`, `fan_wall.scad`, `pi_carrier_column.scad`, `pi_carrier_stack.scad`.
- [ ] Ensure `pi_carrier_stack.scad` imports `pi_carrier.scad` instead of duplicating parameters.
- [ ] Render six STL variants (columns: `printed`, `brass_chain`; fan sizes: 80/92/120) via CI.
- [ ] Create user-facing assembly/BOM documentation once the physical prototype is validated.
- [ ] Verify column alignment with the 58 mm × 49 mm hole rectangle and fan wall spacing within
      ±0.2 mm.
- [ ] Add optional OpenSCAD tests (e.g., `echo()` dimension checks) to aid regression testing.

---

## Appendix A — Key dimensions

- Raspberry Pi board mounting holes: rectangle 58 mm × 49 mm, holes Ø ≈ 2.7 mm; board outline ≈
  85 mm × 56 mm.
- PoE/PoE+ HAT footprint: roughly 65 mm × 56.5 mm; fan 25 mm × 25 mm × 6 mm; height varies by model.
- Fan hole spacings: 120 mm → 105 mm, 92 mm → 82.5 mm, 80 mm → 71.5 mm.
