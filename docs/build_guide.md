# Build Guide

This project uses 20x20 aluminium extrusion to suspend four 100 W solar panels around a cube.
The battery, charge controller, and electronics mount inside a marine battery box and a small
junction box.

1. Print the triple Pi carrier from `cad/pi_cluster` if building a Pi cluster.
   Download pre-rendered STLs from the repository's **Actions** tab: open the
   latest [scad-to-stl workflow run][stl-workflow] and grab the `pi_cluster`
   artifact. To render meshes locally instead, run
   `bash scripts/openscad_render.sh cad/pi_cluster/pi5_triple_carrier_rot45.scad`.
2. Assemble the extrusion cube using M5 hardware, squaring each corner.
3. Mount the solar panels using the printed brackets. Each has a gusset that
   stiffens the corner. Keep panels covered or face-down during wiring to avoid
   live voltage.
4. Attach the battery leads to the MPPT charge controller before any solar
   wiring. Refer to the controller's manual for the recommended connection order
   and connect the load output last. The KiCad schematic and board specs live
   under [elex/power_ring](../elex/power_ring/).
5. Before connecting the array, verify each panel's open-circuit voltage and
   polarity with a multimeter. Join panels with MC4 connectors and 12 AWG wire,
   then attach them to the controller.
6. Install the 12 V air pump and Raspberry Pi on dedicated protection: a 15 A breaker for the pump
   and a 5 A fuse for the Pi. Verify battery voltage with a multimeter before powering devices.
7. Tidy and secure all wiring. Confirm the charge controller shows a charging indicator before
   closing the enclosure.

For details on electronics and safety precautions see [SAFETY.md](SAFETY.md).

[stl-workflow]: https://github.com/futuroptimist/sugarkube/actions/workflows/scad-to-stl.yml
