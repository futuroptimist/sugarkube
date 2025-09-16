# Power Ring Board Specifications

This document outlines the intended features for the Sugarkube power distribution board.
The design may evolve as the project grows.

## Connectors

- **Input:** one pair of screw terminals for 12 V supply
- **Outputs:** four 2-pin JST-VH connectors for branch wiring
- **Mounting holes:** four M3 holes placed on a 40 × 40 mm square

## Protection

- 10 A mini blade fuse on the input
- Optional 5 A fuses on each output (footprints included but unpopulated)

## Extras

- Test points for measuring battery voltage
- Silkscreen labels for polarity and connector numbers
- Fiducial markers to indicate board orientation for easier assembly
- Title block comments record decoupling guidelines, high-current trace layout, thick traces
  for high-current paths, connector labeling, export checks, board outline fit, BOM validation,
  clearance rules for high-voltage nets, star topology to minimize voltage drop, ground pour
  continuity around mounting holes, and fuse orientation checks

These requirements are a starting point – modify the KiCad project as needed and
update this file when the schematic changes.
