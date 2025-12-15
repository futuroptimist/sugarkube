---
title: "Stacked Pi Carrier v2 — modular 3×3 cluster with perpendicular PC-fan wall"
slug: "pi-cluster-stacked-carrier"
personas:
  - hardware
  - cad
owners:
  - futuroptimist
status: published
last_updated: 2025-11-12
---

# Stacked Pi Carrier v2

This document specifies a stackable Raspberry Pi carrier system that reuses the existing
`cad/pi_cluster/pi_carrier.scad` module as a building block and adds:

1. **Vertical stacking** of carriers (three Raspberry Pis per carrier, three carriers tall by
   default).
2. A **perpendicular fan wall** that accepts standard PC fans (80/92/120 mm) via heat-set inserts
   oriented perpendicular to the carrier plates.
3. Print-friendly geometry for **FDM/PLA**, with all parts printable on common beds.

The design integrates with this repository’s OpenSCAD layout and documentation workflow. It now
ships with fabrication guidance so builders can move from CAD to a working cluster without
referencing side-channel notes. The base triple-Pi carrier already exists as
`cad/pi_cluster/pi_carrier.scad`; we import and reuse it rather than reimplementing its details.

---

## Bill of materials

| Item | Qty | Notes |
| --- | ---: | --- |
| `pi_carrier.scad` plates | 3 | Print one plate per level; choose the `standoff_mode` (`heatset`, `through`, or `nut`) that matches your fasteners. |
| Column set (`pi_carrier_stack` columns) | 4 | Print four identical columns; each column spans all levels and accepts radial heat-set inserts or brass standoffs. |
| Fan wall | 1 | Printed from the `fan_wall` module with bosses sized for M3 heat-set inserts. |
| Raspberry Pi 5 boards | 9 | Three per level. |
| M2.5 × 22 mm screws | 12 | Primary fasteners that tie the carriers to the columns. |
| M2.5 heat-set inserts (3.5 mm OD × 4 mm) | 12 | Seat into the column pockets when using the printed-column mode. |
| Brass spacers, M2.5 female–female, 11 mm | 12 | Maintains separation between each Pi and the carrier plate. |
| PC fan (80/92/120 mm) | 1 | Match the fan size to the selected `fan_size` parameter. |
| M3 × 16 mm screws | 4 | Secure the fan to the wall bosses. |
| M3 heat-set inserts (5 mm OD × 4 mm) | 4 | Install in the fan wall bosses. |
| Cable ties or hook-and-loop straps | 6 | Optional strain relief for USB and Ethernet harnesses. |

### Print preparation

- Slice the carriers at 0.2 mm layers with ≥15 % infill; match the surface finish guidance in
  [`docs/pi_cluster_carrier.md`](pi_cluster_carrier.md) for consistent tolerances.
- Print columns upright with three perimeter walls and 40 % gyroid infill. Pause after the first
  2 mm to insert heat-set brass hardware if you prefer captive nuts.
- Print the fan wall on its edge to maximise strength across the insert bosses. Enable tree
  supports or paint-on supports for the boss overhangs if your slicer requires it.
- `openscad` examples:

  ```bash
  # Generate STL assets
  openscad -o stl/pi_carrier_stack_columns.stl cad/pi_cluster/pi_carrier_stack.scad \
    -D export_part="columns"
  openscad -o stl/pi_carrier_stack_fan_wall.stl cad/pi_cluster/pi_carrier_stack.scad \
    -D export_part="fan_wall"
  ```

  CI also renders and publishes STL artifacts via the
  [`Build STL Artifacts` workflow](../.github/workflows/scad-to-stl.yml), which calls
  `scripts/render_pi_cluster_variants.py` to sweep the documented fan sizes and column modes.
  Download the grouped `stl-pi_cluster_stack-${GITHUB_SHA}` artifact for the clearest layout:
  `printed/` and `heatset/` contain the primary stack parts while `variants/` holds the
  fan/column matrix. The legacy `stl-${GITHUB_SHA}` artifact still includes everything if you need
  a single bundle.

---

## Assembly sequence

1. **Prep the carriers.** Follow the insert installation guidance in
   [`docs/pi_cluster_carrier.md`](pi_cluster_carrier.md) to seat M2.5 brass inserts or chase printed
   threads. Install the brass spacers so they are ready for board mounting.
2. **Install column hardware.** Heat the M2.5 inserts and press them into the column pockets at each
   level. For brass-chain builds, thread female–female standoffs together outside the column and
   slide the assembly into place once cool.
3. **Stack the carriers.** Start with the lowest carrier, align a column at each corner, and fasten
   it with an M2.5 screw. Repeat for the remaining levels, ensuring the cable cut-outs line up.
4. **Mount the fan wall.** Align the wall bosses with the column tabs and secure them using the same
   M2.5 screws. Attach the PC fan using the installed M3 inserts and screws, pointing airflow toward
   the Pis.
5. **Cable and verify.** Route power and Ethernet leads down the rear spine, using cable ties for
   strain relief. Power on each Pi sequentially and confirm airflow keeps PoE HAT temperatures below
   60 °C at idle.

Once assembled, the stack occupies a 220 mm × 220 mm footprint with a fan wall offset 15 mm from the
columns. Leave at least 50 mm clearance behind the fan for optimal exhaust flow.

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

## 2. Repository layout

```
cad/pi_cluster/
  fan_patterns.scad        # fan hole spacing helpers (80/92/120)
  fan_wall.scad            # perpendicular fan plate + insert bosses
  pi_carrier_column.scad   # vertical columns (printed or brass-chain)
  pi_carrier_stack.scad    # top-level assembly (stack + fan wall)
docs/
  pi_cluster_stack.md      # design + fabrication guide (this document)
```

The CI renders all `.scad` files into `stl/` via `scripts/openscad_render.sh` and the
pi_carrier_stack fan/column matrix via `scripts/render_pi_cluster_variants.py`. Existing regression
tests under `tests/cad_regress_test.py` automatically exercise the new modules.

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

function fan_square_pattern(size, spacing = fan_hole_spacing(size)) =
    let(half = spacing / 2)
        [
            [-half, -half],
            [half, -half],
            [-half, half],
            [half, half],
        ];
```

Values are derived from common PC fan datasheets (Noctua NF-A12x25, Arctic F9, 80 mm guards).
`fan_square_pattern` returns XY offsets for the square bolt pattern so future fan sizes can reuse the
same layout without duplicating loop logic in consuming modules.

Regression coverage: `tests/test_fan_patterns_scad.py` ensures the helpers stay defined and continue
returning the documented diameters and offsets.

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

Top-level assembly that imports existing modules and composes the stack. Excerpt below shows the
key defaults and helper modules; see the source for the full parameter list and guard logic:

```scad
// STL artifacts + build docs:
// - Spec: docs/pi_cluster_stack.md
// - CI workflow: https://github.com/futuroptimist/sugarkube/actions/workflows/scad-to-stl.yml
// - Artifact: stl-${GITHUB_SHA} (contains stl/pi_cluster/pi_carrier_stack_<mode>_fan{80,92,120}.stl)
_pi_carrier_auto_render = false;
include <./pi_dimensions.scad>;
include <./pi_carrier.scad>;
use <./pi_carrier_column.scad>;
use <./fan_wall.scad>;

levels = is_undef(levels) ? 3 : levels;
z_gap_clear = is_undef(z_gap_clear) ? 32 : z_gap_clear;
column_mode = is_undef(column_mode) ? "printed" : column_mode;
column_od = is_undef(column_od) ? 12 : column_od;
column_wall = is_undef(column_wall) ? 2.4 : column_wall;
carrier_insert_od = is_undef(carrier_insert_od) ? 3.5 : carrier_insert_od;
carrier_insert_L = is_undef(carrier_insert_L) ? 4.0 : carrier_insert_L;
fan_size = is_undef(fan_size) ? 120 : fan_size;
fan_plate_t = is_undef(fan_plate_t) ? 4 : fan_plate_t;
fan_insert_od = is_undef(fan_insert_od) ? 5.0 : fan_insert_od;
fan_insert_L = is_undef(fan_insert_L) ? 4.0 : fan_insert_L;
fan_offset_from_stack = is_undef(fan_offset_from_stack) ? 15 : fan_offset_from_stack;
emit_dimension_report = is_undef(emit_dimension_report) ? false : emit_dimension_report;
stack_standoff_mode = is_undef(standoff_mode) ? "heatset" : standoff_mode;
column_spacing = is_undef(column_spacing) ? pi_hole_spacing : column_spacing;
expected_column_spacing = pi_hole_spacing;
assert(abs(column_spacing[0] - expected_column_spacing[0]) <= 0.2);
assert(abs(column_spacing[1] - expected_column_spacing[1]) <= 0.2);

module _carrier(level) {
  translate([-plate_len / 2, -plate_wid / 2, level * z_gap_clear])
    let(standoff_mode = stack_standoff_mode) pi_carrier();
}

module _columns() {
  for (x = [-column_spacing[0] / 2, column_spacing[0] / 2])
    for (y = [-column_spacing[1] / 2, column_spacing[1] / 2])
      translate([x, y, 0])
        pi_carrier_column(column_mode = column_mode, levels = levels, z_gap_clear = z_gap_clear);
}

module _fan_wall() {
  translate([column_spacing[0] / 2 + fan_offset_from_stack, 0, 0])
    fan_wall(
      fan_size = fan_size,
      fan_plate_t = fan_plate_t,
      fan_insert_od = fan_insert_od,
      fan_insert_L = fan_insert_L,
      levels = levels,
      z_gap_clear = z_gap_clear,
      column_spacing = column_spacing,
      emit_dimension_report = emit_dimension_report
    );
}

module pi_carrier_stack(levels = 3, z_gap_clear = 32, fan_size = 120, standoff_mode = "heatset") {
  _columns();
  for (level = [0 : levels - 1])
    _carrier(level);
  _fan_wall();
}

pi_carrier_stack();
```

- **Columns:** Place four instances at the Pi hole rectangle corners. Tabs on the right-side columns
  expose M3 holes for the fan wall.
- **Fan wall:** Attach using `fan_offset_from_stack` to set the lateral gap. Provide parameters for
  shroud depth and mounting orientation.
- **Echo diagnostics:** Emit key parameters (`levels`, `fan_size`, `column_mode`) to simplify CI logs.
  Regression coverage: `tests/test_pi_carrier_stack_scad.py::test_pi_carrier_stack_imports_pi_carrier_module`
  ensures the assembly reuses `pi_carrier()` instead of placeholder cubes.

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
- Keep the Bill of materials and Assembly sequence sections current as tolerances or hardware
  recommendations change; mirror tone with [`docs/pi_cluster_carrier.md`](pi_cluster_carrier.md).
  Regression coverage: `tests/test_pi_cluster_stack_doc.py`.

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

## 12. Deliverables checklist

All deliverables below now ship with the repository; treat the list as a quick
regression checklist when refreshing the stacked carrier design.

- [x] Add `fan_patterns.scad`, `fan_wall.scad`, `pi_carrier_column.scad`, `pi_carrier_stack.scad`
      under `cad/pi_cluster/`.
- [x] Ensure `pi_carrier_stack.scad` imports `pi_carrier.scad` instead of duplicating parameters.
      (Regression coverage: `tests/test_pi_carrier_stack_scad.py`.)
- [x] Render six STL variants (columns: `printed`, `brass_chain`; fan sizes: 80/92/120) via CI.
      (`scripts/render_pi_cluster_variants.py`, exercised by
      `tests/test_pi_cluster_stl_variants.py`, ensures the matrix renders in automation.)
- [x] Create user-facing assembly/BOM documentation once the physical prototype is validated (see
      [docs/pi_cluster_stack_assembly.md](pi_cluster_stack_assembly.md); regression coverage:
      `tests/test_pi_cluster_stack_assembly_doc.py`).
- [x] Verify column alignment with the 58 mm × 49 mm hole rectangle and fan wall spacing within
      ±0.2 mm. (Regression coverage: `tests/test_pi_cluster_alignment_guards.py`.)
- [x] Add optional OpenSCAD tests (e.g., `echo()` dimension checks) to aid regression
      testing. (Regression coverage:
      `tests/test_pi_cluster_dimension_reports.py::test_dimension_report_echo_is_declared`,
      `tests/test_pi_cluster_dimension_reports.py::test_dimension_report_echo_outputs_expected_keys`.)

---

## Appendix A — Key dimensions

- Raspberry Pi board mounting holes: rectangle 58 mm × 49 mm, holes Ø ≈ 2.7 mm; board outline ≈
  85 mm × 56 mm.
- PoE/PoE+ HAT footprint: roughly 65 mm × 56.5 mm; fan 25 mm × 25 mm × 6 mm; height varies by model.
- Fan hole spacings: 120 mm → 105 mm, 92 mm → 82.5 mm, 80 mm → 71.5 mm.
