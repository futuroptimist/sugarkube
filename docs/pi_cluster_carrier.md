---
personas:
  - hardware
---

# Pi Cluster Carrier

This design mounts three Raspberry Pi 5 boards on a common plate. Each Pi is rotated 45° so the USB and Ethernet ports remain accessible. By default the boards are arranged in a 2×2 grid with one corner empty so the plate fits on printers with a 256 mm build area (e.g. the Bambu Lab A1). Brass heat‑set inserts can be used for durability, or you can print threads directly.

The base corners are rounded with a configurable `corner_radius` parameter (default 5 mm) to soften sharp edges.

The model lives at `cad/pi_cluster/pi5_triple_carrier_rot45.scad`. STL files for
heat‑set, printed-thread, and captive-nut variants are produced by GitHub Actions and
published as artifacts whenever the SCAD file changes. You can edit the `pi_positions`
array near the top of the file to tweak the arrangement if your printer allows a larger
build area.
Captive-nut pockets include 0.4 mm of extra clearance to make nut insertion easier.
For an overview of insert installation and printed threads see [insert_basics.md](insert_basics.md).


Use OpenSCAD to preview and tweak parameters:

```bash
openscad cad/pi_cluster/pi5_triple_carrier_rot45.scad
```

To render one variant manually:

```bash
# brass insert version
openscad -D standoff_mode="heatset" \
  -o triple.stl cad/pi_cluster/pi5_triple_carrier_rot45.scad
# printed-thread version
openscad -D standoff_mode="printed" \
  -o triple_printed.stl cad/pi_cluster/pi5_triple_carrier_rot45.scad
# captive-nut version
openscad -D standoff_mode="nut" \
  -o triple_nut.stl cad/pi_cluster/pi5_triple_carrier_rot45.scad
```

See the main [build guide](build_guide.md) for assembly details.

## Mounting hardware

For the strongest hold install brass heat‑set inserts in each printed
standoff. Use a single long screw per corner that threads down through
an 11 mm brass spacer and the Pi board into the insert. This keeps the
underside flat and lets you stack an M.2 HAT or other accessory on top.

| Part   | Spec                                 | Example listing                          |
| ------ | ------------------------------------ | ---------------------------------------- |
| Screw  | **M2.5 × 22 mm pan head**            | "M2.5×22 Phillips pan head"              |
| Spacer | M2.5 female‑female, 11 mm long       | "M2.5×11 mm brass hex standoff"          |
| Insert | M2.5 heat‑set, 3.5 mm OD × 4 mm long | "M2.5 × D3.5 × L4 brass insert" |

- These dimensions match common brass inserts (3.5 mm outer diameter, 4 mm length). Using a 22 mm screw guarantees at least 3 mm of bite in the insert even if your brass spacer is slightly oversized or you add a washer.

Screw from the top and gently tighten until the screw stops against the
blind insert. If you prefer screws from the bottom, print the
`through` variant instead and use M2.5 × 10 mm screws up into the same
spacers.
