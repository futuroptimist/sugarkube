# Build Guide

This project uses 20x20 aluminium extrusion to suspend four 100 W solar panels around a cube.
The battery, charge controller, and electronics mount inside a marine battery box and a small
junction box.

1. Print the triple Pi carrier from `cad/pi_cluster` if building a Pi cluster.
   Download STL files for either insert variant from the latest
   [scad-to-stl workflow run][stl-workflow] in GitHub Actions.
2. Assemble the extrusion cube using M5 hardware.
3. Mount the solar panels using the printed brackets.
   Each has a gusset that stiffens the corner.
4. Attach the battery leads to the MPPT charge controller before any solar wiring. Refer to the
   controller's manual for the recommended connection order. The KiCad schematic and board specs
   live under [elex/power_ring](../elex/power_ring/).
5. Wire the solar panels to the controller once the battery is present, observing polarity.
6. Install the 12 V air pump and Raspberry Pi on dedicated protection: a 15 A breaker for the pump
   and a 5 A fuse for the Pi. Verify battery voltage with a multimeter before powering devices.

For details on electronics and safety precautions see [SAFETY.md](SAFETY.md).

[stl-workflow]: https://github.com/futuroptimist/sugarkube/actions/workflows/scad-to-stl.yml
