# Build Guide

This project uses 20x20 aluminium extrusion to suspend four 100W solar panels around a cube.  The battery, charge controller and electronics mount inside a marine battery box and small junction box.

1. Print the brackets from `cad/solar_cube`.
2. Print the triple Pi carrier from `cad/pi_cluster` if building a Pi cluster.
   STL files are generated automatically under `stl/`.
3. Assemble the extrusion cube using M5 hardware.
4. Mount the solar panels using the printed brackets.
5. Wire the panels to the Victron MPPT charge controller as shown in the `elex/power_ring` schematic.
6. Install the 12V air pump and Raspberry Pi behind a 15A breaker and 5A fuse respectively.
7. Connect the battery and verify voltage before powering devices.

For details on electronics and safety precautions see [SAFETY.md](SAFETY.md).
