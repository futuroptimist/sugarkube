# Pi Cluster Carrier

This design mounts three Raspberry Pi 5 boards side by side on a common plate.  Each Pi is rotated 45° so the USB and Ethernet ports remain accessible.  Brass heat‑set inserts can be used for durability, or you can print threads directly.

The model lives at `cad/pi_cluster/pi5_triple_carrier_rot45.scad`.  STL files for both heat‑set and printed‑thread variants are generated automatically under `stl/` by GitHub Actions whenever the SCAD file changes.

Use OpenSCAD to preview and tweak parameters:

```bash
openscad cad/pi_cluster/pi5_triple_carrier_rot45.scad
```

To render one variant manually:

```bash
# brass insert version
openscad -D standoff_mode="heatset" -o triple.stl cad/pi_cluster/pi5_triple_carrier_rot45.scad
# printed-thread version
openscad -D standoff_mode="printed"  -o triple_printed.stl cad/pi_cluster/pi5_triple_carrier_rot45.scad
```

See the main [build guide](build_guide.md) for assembly details.
