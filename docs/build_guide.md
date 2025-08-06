# Build Guide

This project uses 20x20 aluminium extrusion to suspend four 100 W solar panels around a cube.
The battery, charge controller, and electronics mount inside a marine battery box and a small
junction box.

1. Print the triple Pi carrier from `cad/pi_cluster` if building a Pi cluster. STL files for both
   insert variants are published as artifacts by GitHub Actions.
2. Assemble the extrusion cube using M5 hardware.
3. Mount the solar panels using the printed brackets.
4. Wire the panels to the Victron MPPT charge controller. The KiCad schematic and board specs
   live under [elex/power_ring](../elex/power_ring/).
5. Install the 12 V air pump and Raspberry Pi behind a 15 A breaker and 5 A fuse respectively.
6. Connect the battery and verify voltage before powering devices.

For details on electronics and safety precautions see [SAFETY.md](SAFETY.md).
