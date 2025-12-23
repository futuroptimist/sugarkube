---
title: "Stacked Pi Carrier v2 — modular 3×3 cluster with perpendicular PC-fan wall"
slug: "pi-cluster-stacked-carrier"
personas:
  - hardware
  - cad
owners:
  - futuroptimist
status: published
last_updated: 2025-12-21
---

# Stacked Pi Carrier v2

This document specifies a stackable Raspberry Pi carrier system that reuses the existing
`cad/pi_cluster/pi_carrier.scad` module as a building block and adds:

> **Temporary status (December 2025):** the stack wrapper now renders **carrier plates + four
> full-height corner posts** (one per corner stack mount). The printed fan adapter and fan wall are
> still intentionally omitted from the preview while their geometry is refined. Export modes
> `fan_adapter` and `fan_wall` therefore do not emit their expected meshes right now; they will
> return once the geometry is reintroduced.

1. **Vertical stacking** of carriers (three Raspberry Pis per carrier, three carriers tall by
   default).
2. Four **stack clamp mounts** per carrier (M3 through-holes + symmetric locating pockets) sized
   for four **full-height corner posts** that key into each carrier level and maintain the gap.
3. A future **perpendicular fan wall** that accepts standard PC fans (80/92/120 mm) via heat-set
   inserts oriented perpendicular to the carrier plates.
4. Print-friendly geometry for **FDM/PLA**, with all parts printable on common beds.

The design integrates with this repository’s OpenSCAD layout and documentation workflow. The base
triple-Pi carrier already exists as `cad/pi_cluster/pi_carrier.scad`; we import and reuse it rather
than reimplementing its details.

---

## Bill of materials

| Item | Qty | Notes |
| --- | ---: | --- |
| `pi_carrier.scad` plates | 3 | Print one plate per level; stack renders (`pi_carrier_stack.scad` with `export_part="carrier_level"`) add the stack clamp through-holes plus symmetric locating pockets on both faces. |
| Full-height corner posts (`pi_stack_post.scad`) | 4 | One per corner. Each post spans the entire stack height (derived from `levels`, `z_gap_clear`, and `plate_thickness`) and includes slot cutouts derived from the carrier plate dimensions (fast rectangular profile by default) so carrier geometry changes propagate automatically. |
| M3 × 90 mm screws + nuts | 4 | Clamp the plates and posts together. Length depends on `levels`, `z_gap_clear`, plate thickness, and how much nut-trap depth you use on the post. Washers recommended. |
| M2.5 heat-set inserts (3.5 mm OD × 4 mm) | 36 | Seat into the carrier standoffs for all 9 Pis (4 per Pi). |
| Brass spacers, M2.5 female–female, 11 mm | 36 | Four per Pi (one per mounting point), for all 9 Pis in the stack. Maintains separation between each Pi and the carrier plate. |
| Raspberry Pi 5 boards | 9 | Three per level. |
| PC fan (80/92/120 mm) | 1 | Fan wall is currently omitted from the CAD preview; this remains the intended thermal path. |
| (Future) Fan adapter (`pi_stack_fan_adapter.scad`) | 1 | Not currently emitted by the stack wrapper preview. |
| (Future) Fan wall | 1 | Not currently emitted by the stack wrapper preview. |
| (Future) M3 hardware for fan wall | — | To be reintroduced when fan geometry returns. |

### Print preparation

- Slice the carriers at 0.2 mm layers with ≥15 % infill; match the surface finish guidance in
  [`docs/pi_cluster_carrier.md`](pi_cluster_carrier.md) for consistent tolerances.
- Stack-ready carrier levels rendered via `pi_carrier_stack.scad` default to a 3.0 mm plate and
  expand the perimeter margin to 15 mm. This keeps the 1.2 mm symmetric locating pockets (Ø9 mm) and
  clamp through-holes clear of the Pi keep-out zones; the standalone `pi_carrier.scad` remains a
  2.0 mm plate for non-stacked builds.
- Print the corner posts upright with three perimeter walls and 30–40 % infill. The posts:
  - include a bottom M3 nut-trap by default,
- include carrier-derived rectangular slot cutouts at each level,
  - include a small lead-in relief on the slot edges to reduce elephant-foot frustration during
    assembly,
  - expose a `fit_clearance` / `post_fit_clearance` tolerance knob (default ~0.2 mm).
- Install heat-set inserts after printing. Install the M2.5 heat-set inserts in the carrier
  standoffs.

- `openscad` examples (fan components temporarily disabled—see note above):

  ```bash
  # Generate a single carrier level (print 3x)
  openscad -o stl/pi_cluster/pi_carrier_stack_carrier_level_heatset.stl cad/pi_cluster/pi_carrier_stack.scad \
    -D export_part="carrier_level" -D standoff_mode="heatset" -D stack_edge_margin=15

  # Generate a single corner post STL (print 4x)
  openscad -o stl/pi_cluster/pi_carrier_stack_post.stl cad/pi_cluster/pi_carrier_stack.scad \
    -D export_part="post" -D stack_bolt_d=3.4

  # Full assembly preview (carriers + 4 posts)
  openscad -o /tmp/pi_carrier_stack_preview.stl cad/pi_cluster/pi_carrier_stack.scad \
    -D export_part="assembly"
  ```

  Cross-platform quoting for part selection:

  - Bash / zsh (single carrier level + dimension echo):

    ```bash
    openscad -o /tmp/pi_carrier_stack_level.stl \
      -D export_part="carrier_level" \
      -D emit_dimension_report=true \
      cad/pi_cluster/pi_carrier_stack.scad
    ```

  - PowerShell (same invocation; emits `export_part = carrier_level` without warnings):

    ```powershell
    openscad `
      -o "$env:TEMP\pi_carrier_stack_level.stl" `
      -D 'export_part="carrier_level"' `
      -D 'emit_dimension_report=true' `
      -- cad/pi_cluster/pi_carrier_stack.scad
    ```

  Both commands should echo `pi_carrier_stack` with `export_part = carrier_level` and avoid
  "Ignoring unknown variable" warnings.

  CI also renders and publishes STL artifacts via the
  [`Build STL Artifacts` workflow](../.github/workflows/scad-to-stl.yml), which calls
  `scripts/render_pi_cluster_variants.py` to sweep the documented fan sizes and produce stack STLs.
  Download the grouped stack bundle named `stl-pi_cluster_stack-${GITHUB_SHA}`; it contains
  stack-specific STLs organised as `printed/`, `heatset/`, `variants/`, plus `carriers/`, `posts/`,
  and `preview/`. The legacy monorepo bundle `stl-${GITHUB_SHA}` remains available but the grouped
  stack artifact is preferred.

## Debugging / Diagnostics

- `preview_stack_mounts` is a single-line toggle in
  [`pi_carrier.scad`](pi_cluster_carrier.md) that locally enables stack mounts without touching
  other parameters. If `include_stack_mounts` is defined (for example when
  `pi_carrier_stack.scad` imports the carrier), that explicit value wins.
- Prefer `export_part="carrier_level"` for fast carrier iteration; it renders a single carrier level
  with stack mounts enabled.
- Prefer `export_part="post"` for fast post iteration; it renders one post (print four copies).
- `emit_geometry_report=true` on `pi_carrier.scad` surfaces a human-readable `"pi_carrier_geometry"`
  echo with plate sizing (`plate_len`, `plate_wid`, `plate_outer_bounds_*`) and stack mount placement
  details (insets, center/margin checks, and the resolved positions). Pair it with
  `emit_dimension_report=true` on `pi_carrier_stack.scad` to also emit the top-level stack
  dimensions.
- Example commands:

  ```bash
  openscad -o /tmp/pi_carrier.stl -D emit_geometry_report=true cad/pi_cluster/pi_carrier.scad
  openscad -o /tmp/pi_carrier_mounts.stl -D preview_stack_mounts=true -D emit_geometry_report=true \
    cad/pi_cluster/pi_carrier.scad

  # Stack wrapper (single carrier level)
  openscad -o /tmp/pi_carrier_stack_level.stl -D export_part="carrier_level" \
    -D emit_dimension_report=true -D emit_geometry_report=true cad/pi_cluster/pi_carrier_stack.scad

  # Stack wrapper (single post)
  openscad -o /tmp/pi_carrier_stack_post.stl -D export_part="post" \
    -D emit_dimension_report=true cad/pi_cluster/pi_carrier_stack.scad
  ```

CI parses selected echoes for regression coverage; see
`tests/test_pi_carrier_geometry_report.py` and `tests/test_pi_carrier_stack_geometry_report.py` for
the enforced invariants.

---

## Assembly sequence

1. **Prep the carriers.** Follow the insert installation guidance in
   [`docs/pi_cluster_carrier.md`](pi_cluster_carrier.md) to seat M2.5 brass inserts (or chase printed
   threads if you are using `standoff_mode="printed"`). Install the brass spacers so they are ready
   for board mounting.
2. **Prep the posts.** Press an M3 nut into the nut trap on the bottom of each corner post (or
   plan to use a washer + nut on the outside if you disabled nut traps).
3. **Stage the stack.** Arrange the four posts around the footprint so their carrier cutouts face
   inward. Slide the bottom carrier plate into the lowest cutouts on all four posts.
4. **Add the remaining carriers.** Slide the middle carrier into the next cutouts, then slide the
   top carrier into the top cutouts. The post cutouts are located at fixed Z intervals derived from
   `z_gap_clear` and plate thickness, so the carrier spacing is automatic.
5. **Clamp with bolts.** Insert four long M3 bolts through the top carrier stack-mount holes and
   down through the post bores. Tighten into the captured nuts (or onto bottom nuts) to clamp the
   entire stack.
6. **Mount boards and cable.** Mount each Pi to its carrier using the existing standoff + spacer
   hardware. Route power and Ethernet harnesses along the stack perimeter; add cable ties for strain
   relief.

Once assembled, the stack footprint increases only slightly beyond the carrier plate due to the
post overhang; tune `post_overhang` if you want more outside meat or a tighter envelope.

---

## 1. Context and constraints

- **Boards & holes.** Raspberry Pi 5/4 outline ≈ 85 mm × 56 mm with M2.5 mounting holes on a
  58 mm × 49 mm rectangle (Ø ≈ 2.7 mm). Use these dimensions for column placement and clearances.
- **PoE HAT clearance.** Official PoE/PoE+ HATs include a 25 mm fan and top-side components; do not
  obstruct the intake. Default vertical spacing should assume *HAT height + intake margin*.
- **Fan standards (future fan wall).** Support the following center-to-center mounting hole patterns
  out of the box:
  - 120 mm fan → 105 mm × 105 mm pattern (e.g., Noctua NF-A12x25).
  - 92 mm fan → 82.5 mm × 82.5 mm pattern (e.g., Arctic F9).
  - 80 mm fan → 71.5 mm × 71.5 mm pattern (common guards and filters).
- **Repository interfaces.**
  - Reuse `pi_carrier.scad` (triple-Pi base with `standoff_mode` variants: `heatset`, `through`,
    `nut`) and its parameters (`corner_radius`, `gap_between_boards`, etc.).
  - Keep documentation consistent with `docs/pi_cluster_carrier.md` tone and structure.
  - Follow `docs/prompts/codex/implement.md` when turning this spec into code so new parts pass CI
    and STL rendering.

---

## 2. Repository layout

```text
cad/pi_cluster/
  fan_patterns.scad        # fan hole spacing helpers (80/92/120)
  fan_wall.scad            # perpendicular fan plate + insert bosses
  pi_carrier_column.scad   # vertical columns (printed or brass-chain)
  pi_carrier_stack.scad    # top-level assembly (stack + posts + (future) fan wall)
  pi_stack_post.scad       # full-height corner post keyed off pi_carrier geometry
docs/
  pi_cluster_stack.md      # design + fabrication guide (this document)
```

The CI renders all `.scad` files into `stl/` via `scripts/openscad_render.sh` and the
pi_carrier_stack matrix via `scripts/render_pi_cluster_variants.py`.

---

## 3. Parameters (top level)

All dimensions are in millimetres unless otherwise noted.

| Parameter | Default | Purpose |
| --- | ---: | --- |
| `levels` | 3 | Number of carriers stacked vertically. |
| `standoff_mode` | `"heatset"` | Forwarded to `pi_carrier.scad` for board standoffs. |
| `z_gap_clear` | 32 | Vertical gap between carrier plates; typically `poe_hat_height + intake_margin`. |
| `stack_edge_margin` | 15 | Carrier plate edge padding in stack mode (keeps pockets clear). |
| `stack_pocket_d` | 9 | Locating pocket diameter (carrier). |
| `stack_pocket_depth` | 1.2 | Pocket depth on each face (carrier). |
| `stack_bolt_d` | 3.4 | Through-hole diameter for the stack clamp bolts (M3 clearance). |
| `post_body_d` | 26 | Corner post cylinder diameter. |
| `post_overhang` | 5 | How far the post body extends beyond the carrier outer edge. |
| `post_fit_clearance` | 0.2 | Extra XY clearance applied to the carrier-derived rectangular slot cutouts in the post. |
| `post_leadin_depth` | 0.8 | Z-depth of the lead-in relief at each slot edge inside the post cutout. |

Notes:

- `post_fit_clearance` is intentionally small; too large makes the stack feel sloppy.
- The post cutouts are generated by subtracting `pi_carrier()` at each level, so carrier geometry
  changes propagate automatically.

---

## 4. Module design

### 4.1 `pi_stack_post.scad`

The post is a single printed part per corner. It:

- spans the full stack height,
- includes a bolt bore aligned to the carrier’s stack-mount centers,
- subtracts the carrier geometry at each level to form level-indexed slots,
- applies a small lead-in relief on the slot edges.

### 4.2 `pi_carrier_stack.scad`

The stack wrapper now composes:

- four posts (one per stack-mount corner),
- `levels` carrier plates placed at `level * (z_gap_clear + plate_thickness)`.

Export modes:

- `export_part="carrier_level"` → one carrier level (print 3×).
- `export_part="post"` → one post (print 4×).
- `export_part="assembly"` → carriers + posts preview.

(Fan wall components remain disabled until their geometry is reintroduced.)

---

## 5. Print guidance (FDM/PLA)

- Material: PLA (or PETG if ambient temperature exceeds 35 °C).
- Layer height: 0.2 mm. Perimeters: ≥4. Infill: 30–40 % gyroid.
- **Corner posts:** Print upright. If you see tight fits, increase `post_fit_clearance` by 0.05–0.10.
- **Carrier plates:** Continue printing via existing `pi_carrier.scad` defaults.
- Heat-set inserts: For M2.5 inserts with 3.5 mm OD × 4 mm length, size pockets with ~0.2 mm
  interference (hole ≈ 3.3 mm). Match current carrier defaults for consistency.

---

## 6. Hardware (per 3×3 stack)

- **Per Raspberry Pi (×9):** M2.5 × 22 pan-head screw + M2.5 11 mm brass spacer.
- **Stack clamp:** four long M3 bolts + nuts (or nut traps in the posts).
- **Future fan wall:** M3 heat-set inserts + M3 screws (pending reintroduction).

---

## 7. Thermal intent & placement (future fan wall)

- Orient the fan to blow across PoE-HAT intakes without creating recirculation; maintain at least
  8–10 mm clearance from obstructions (enforced via `intake_margin`).
- Prefer 120 mm fans for best CFM/dBA; 92 mm and 80 mm remain options for tighter envelopes.
- Fan plate mounting holes target M3 clearance (Ø3.2–3.4 mm) for the future perpendicular wall.

---

## 8. Acceptance criteria

**CAD & CI**

- New/updated SCAD files compile locally and via CI to STL artifacts without OpenSCAD warnings.
- `pi_carrier_stack.scad` renders at least:
  - carriers (`carrier_level`)
  - posts (`post`)
  - full preview (`assembly`)

**Geometry checks**

- Carrier plate dimensions remain invariant to stack mount inclusion (enforced by carrier code).
- Post cutouts align to carrier geometry at each level for the chosen `levels`, `z_gap_clear`, and
  plate thickness.

**Print & assembly**

- 4 corner posts + 3 carrier plates assemble without forcing.
- Nuts seat cleanly in the post nut traps.

---

## 12. Deliverables checklist

- [x] Create user-facing assembly/BOM documentation (see `docs/pi_cluster_stack_assembly.md`).
- [x] `cad/pi_cluster/pi_carrier_stack.scad` and `cad/pi_cluster/pi_stack_post.scad` generate carrier
  levels, single posts, and full-stack previews via `export_part`.
- [x] CI publishes grouped stack STL artifacts (`stl-pi_cluster_stack-${GITHUB_SHA}`) with
  `printed/`, `heatset/`, and `variants/` layouts for direct download.
- [x] This document and `docs/pi_cluster_carrier.md` describe assembly and cross-link the carrier
  field guide for tolerances and insert guidance.

---

## Appendix A — Key dimensions

- Raspberry Pi board mounting holes: rectangle 58 mm × 49 mm, holes Ø ≈ 2.7 mm; board outline ≈
  85 mm × 56 mm.
- Fan hole spacings (future): 120 mm → 105 mm, 92 mm → 82.5 mm, 80 mm → 71.5 mm.
